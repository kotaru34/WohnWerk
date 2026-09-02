from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.jobs.admin_store import (
    add_manual_alias,
    delete_manual_alias,
    list_concepts_for_admin,
    reset_preference_to_seed,
    set_alias_enabled,
    set_manual_preference,
)
from app.jobs.candidate_fit import CandidatePreferenceState
from app.jobs.candidate_job_store import set_job_favorite, set_job_hidden
from app.jobs.candidate_profile_store import get_seed_profile
from app.jobs.concepts import ConceptKind
from app.jobs.fit_store import annual_salary_label, load_live_job_fit

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBasic(auto_error=False)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

KIND_LABELS = {
    ConceptKind.ROLE: "Rolle",
    ConceptKind.DOMAIN: "Fachgebiet",
    ConceptKind.TASK: "Aufgabe",
    ConceptKind.METHOD: "Methode",
    ConceptKind.TOOL: "Werkzeug",
}
KIND_LABELS_BY_VALUE = {kind.value: label for kind, label in KIND_LABELS.items()}
STATE_LABELS = {
    CandidatePreferenceState.CAN_WANT: "Kann ich / möchte ich",
    CandidatePreferenceState.CAN_NOT_WANT: "Kann ich / möchte ich nicht",
    CandidatePreferenceState.CANNOT_WANT: "Kann ich nicht / möchte ich",
    CandidatePreferenceState.CANNOT_NOT_WANT: "Kann ich nicht / möchte ich nicht",
}
CONCEPT_RATING_FILTERS = {
    "alle": "Alle",
    "bewertet": "Bewertet",
    "unbewertet": "Unbewertet",
}
JOB_FILTERS = {
    "passend": "Passend",
    "favoriten": "Favoriten",
    "alle": "Alle",
    "unvereinbar": "Unvereinbar",
    "unbewertet": "Unbewertet",
    "ausgeblendet": "Ausgeblendet",
}

CredentialsDependency = Annotated[HTTPBasicCredentials | None, Depends(security)]
DbDependency = Annotated[Session, Depends(get_db)]


def _configured_admin_settings():
    settings = get_settings()
    if not settings.admin_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin-Oberfläche ist nicht konfiguriert.",
        )
    return settings


def _secure_equal(left: str, right: str) -> bool:
    return secrets.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _csrf_token() -> str:
    settings = _configured_admin_settings()
    return hmac.new(
        settings.admin_password.encode("utf-8"),
        b"wohnwerk-admin-csrf-v1",
        hashlib.sha256,
    ).hexdigest()


def require_admin(credentials: CredentialsDependency) -> None:
    settings = _configured_admin_settings()
    valid = (
        credentials is not None
        and _secure_equal(credentials.username, settings.admin_username)
        and _secure_equal(credentials.password, settings.admin_password)
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Zugangsdaten.",
            headers={"WWW-Authenticate": 'Basic realm="WohnWerk Admin"'},
        )


def require_csrf(csrf_token: Annotated[str, Form()]) -> None:
    if not _secure_equal(csrf_token, _csrf_token()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ungültiger Formularschutz.",
        )


AdminDependency = Annotated[None, Depends(require_admin)]
CsrfDependency = Annotated[None, Depends(require_csrf)]


def _profile_or_503(db: Session):
    profile = get_seed_profile(db)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Kandidatenprofil ist noch nicht initialisiert.",
        )
    return profile


def _kind_or_none(value: str | None) -> ConceptKind | None:
    if not value:
        return None
    try:
        return ConceptKind(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Ungültiger Konzepttyp.") from exc


def _is_manually_rated(row) -> bool:
    return row.preference is not None and row.preference.source == "manual"


def _concept_redirect(
    concept_id: int,
    *,
    kind: str = "",
    rating: str = "alle",
    aliases_changed: bool = False,
):
    query: dict[str, str] = {}
    if kind:
        query["kind"] = kind
    if rating != "alle":
        query["bewertung"] = rating
    if aliases_changed:
        query["hinweis"] = "normalisierung"
    suffix = f"?{urlencode(query)}" if query else ""
    return RedirectResponse(f"/admin/concepts{suffix}#concept-{concept_id}", status_code=303)


def _job_redirect(job_id: int, *, view: str, search: str):
    query = {"ansicht": view}
    if search.strip():
        query["suche"] = search.strip()
    return RedirectResponse(f"/admin/jobs?{urlencode(query)}#job-{job_id}", status_code=303)


@router.get("/concepts")
def concepts_page(
    request: Request,
    _: AdminDependency,
    db: DbDependency,
    kind: Annotated[str | None, Query()] = None,
    bewertung: Annotated[str, Query()] = "alle",
    hinweis: Annotated[str | None, Query()] = None,
):
    profile = _profile_or_503(db)
    selected_kind = _kind_or_none(kind)
    if bewertung not in CONCEPT_RATING_FILTERS:
        raise HTTPException(status_code=400, detail="Ungültiger Bewertungsfilter.")

    all_rows = list_concepts_for_admin(db, profile, kind=selected_kind)
    rated_count = sum(_is_manually_rated(row) for row in all_rows)
    stats = {
        "gesamt": len(all_rows),
        "bewertet": rated_count,
        "unbewertet": len(all_rows) - rated_count,
    }
    rows = all_rows
    if bewertung == "bewertet":
        rows = [row for row in rows if _is_manually_rated(row)]
    elif bewertung == "unbewertet":
        rows = [row for row in rows if not _is_manually_rated(row)]

    return templates.TemplateResponse(
        request=request,
        name="admin_concepts.html",
        context={
            "profile": profile,
            "rows": rows,
            "concept_stats": stats,
            "kinds": list(ConceptKind),
            "kind_labels": KIND_LABELS,
            "kind_labels_by_value": KIND_LABELS_BY_VALUE,
            "selected_kind": selected_kind,
            "concept_rating_filters": CONCEPT_RATING_FILTERS,
            "selected_rating": bewertung,
            "state_labels": STATE_LABELS,
            "preference_states": list(CandidatePreferenceState),
            "normalization_notice": hinweis == "normalisierung",
            "csrf_token": _csrf_token(),
        },
    )


@router.get("/jobs")
def jobs_page(
    request: Request,
    _: AdminDependency,
    db: DbDependency,
    ansicht: Annotated[str, Query()] = "passend",
    suche: Annotated[str, Query()] = "",
):
    profile = _profile_or_503(db)
    if ansicht not in JOB_FILTERS:
        raise HTTPException(status_code=400, detail="Ungültige Stellenansicht.")

    all_rows = load_live_job_fit(db, profile_slug=profile.slug)
    stats = {
        "gesamt": len(all_rows),
        "bewertet": sum(row.result.score is not None for row in all_rows),
        "unvereinbar": sum(bool(row.result.hard_constraints) for row in all_rows),
        "unbewertet": sum(row.result.score is None for row in all_rows),
        "favoriten": sum(row.favorite for row in all_rows),
        "ausgeblendet": sum(row.hidden for row in all_rows),
    }

    rows = all_rows
    if ansicht == "passend":
        rows = [
            row
            for row in rows
            if not row.hidden
            and row.result.score is not None
            and not row.result.hard_constraints
        ]
    elif ansicht == "favoriten":
        rows = [row for row in rows if row.favorite]
    elif ansicht == "alle":
        rows = [row for row in rows if not row.hidden]
    elif ansicht == "unvereinbar":
        rows = [row for row in rows if not row.hidden and row.result.hard_constraints]
    elif ansicht == "unbewertet":
        rows = [row for row in rows if not row.hidden and row.result.score is None]
    elif ansicht == "ausgeblendet":
        rows = [row for row in rows if row.hidden]

    normalized_search = suche.strip().casefold()
    if normalized_search:
        rows = [
            row
            for row in rows
            if normalized_search in row.job.title.casefold()
            or normalized_search in (row.job.company or "").casefold()
            or any(normalized_search in location.casefold() for location in row.locations)
        ]

    return templates.TemplateResponse(
        request=request,
        name="admin_jobs.html",
        context={
            "profile": profile,
            "rows": rows,
            "stats": stats,
            "job_filters": JOB_FILTERS,
            "selected_filter": ansicht,
            "search": suche,
            "annual_salary_label": annual_salary_label,
            "csrf_token": _csrf_token(),
        },
    )


@router.post("/concepts/{concept_id}/preference")
def set_preference(
    concept_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    state_value: Annotated[str, Form(alias="state")],
    return_kind: Annotated[str, Form()] = "",
    return_rating: Annotated[str, Form()] = "alle",
):
    profile = _profile_or_503(db)
    try:
        preference_state = CandidatePreferenceState(state_value)
        set_manual_preference(db, profile, concept_id, preference_state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Ungültiger Bewertungszustand.") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Konzept nicht gefunden.") from exc
    return _concept_redirect(concept_id, kind=return_kind, rating=return_rating)


@router.post("/concepts/{concept_id}/preference/reset")
def reset_preference(
    concept_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    return_kind: Annotated[str, Form()] = "",
    return_rating: Annotated[str, Form()] = "alle",
):
    profile = _profile_or_503(db)
    try:
        reset_preference_to_seed(db, profile, concept_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Konzept nicht gefunden.") from exc
    return _concept_redirect(concept_id, kind=return_kind, rating=return_rating)


@router.post("/concepts/{concept_id}/aliases")
def add_alias(
    concept_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    alias: Annotated[str, Form()],
    language: Annotated[str, Form()] = "",
    return_kind: Annotated[str, Form()] = "",
    return_rating: Annotated[str, Form()] = "alle",
):
    try:
        add_manual_alias(db, concept_id, alias, language=language or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Alias darf nicht leer sein.") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Konzept nicht gefunden.") from exc
    return _concept_redirect(
        concept_id,
        kind=return_kind,
        rating=return_rating,
        aliases_changed=True,
    )


@router.post("/aliases/{alias_id}/toggle")
def toggle_alias(
    alias_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    concept_id: Annotated[int, Form()],
    enabled: Annotated[str, Form()],
    return_kind: Annotated[str, Form()] = "",
    return_rating: Annotated[str, Form()] = "alle",
):
    try:
        set_alias_enabled(db, alias_id, enabled=enabled == "1")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Synonym nicht gefunden.") from exc
    return _concept_redirect(
        concept_id,
        kind=return_kind,
        rating=return_rating,
        aliases_changed=True,
    )


@router.post("/aliases/{alias_id}/delete")
def remove_alias(
    alias_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    concept_id: Annotated[int, Form()],
    return_kind: Annotated[str, Form()] = "",
    return_rating: Annotated[str, Form()] = "alle",
):
    try:
        delete_manual_alias(db, alias_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Synonym nicht gefunden.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Standard-Synonyme können nur deaktiviert werden.") from exc
    return _concept_redirect(
        concept_id,
        kind=return_kind,
        rating=return_rating,
        aliases_changed=True,
    )


@router.post("/jobs/{job_id}/favorite")
def update_job_favorite(
    job_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    favorite: Annotated[str, Form()],
    return_view: Annotated[str, Form()] = "passend",
    return_search: Annotated[str, Form()] = "",
):
    profile = _profile_or_503(db)
    if return_view not in JOB_FILTERS:
        return_view = "passend"
    try:
        set_job_favorite(db, profile, job_id, favorite=favorite == "1")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Stelle nicht gefunden.") from exc
    return _job_redirect(job_id, view=return_view, search=return_search)


@router.post("/jobs/{job_id}/hidden")
def update_job_hidden(
    job_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    hidden: Annotated[str, Form()],
    return_view: Annotated[str, Form()] = "passend",
    return_search: Annotated[str, Form()] = "",
):
    profile = _profile_or_503(db)
    if return_view not in JOB_FILTERS:
        return_view = "passend"
    try:
        set_job_hidden(db, profile, job_id, hidden=hidden == "1")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Stelle nicht gefunden.") from exc
    return _job_redirect(job_id, view=return_view, search=return_search)
