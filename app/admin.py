from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated

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
from app.jobs.candidate_profile_store import get_seed_profile
from app.jobs.concepts import ConceptKind

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

CredentialsDependency = Annotated[HTTPBasicCredentials | None, Depends(security)]
DbDependency = Annotated[Session, Depends(get_db)]


def require_admin(credentials: CredentialsDependency) -> None:
    settings = get_settings()
    if not settings.admin_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin-Oberfläche ist nicht konfiguriert.",
        )
    valid = credentials is not None and secrets.compare_digest(
        credentials.username, settings.admin_username
    ) and secrets.compare_digest(credentials.password, settings.admin_password)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige Zugangsdaten.",
            headers={"WWW-Authenticate": 'Basic realm="WohnWerk Admin"'},
        )


AdminDependency = Annotated[None, Depends(require_admin)]


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


def _redirect(concept_id: int, *, kind: str = "", aliases_changed: bool = False):
    query = []
    if kind:
        query.append(f"kind={kind}")
    if aliases_changed:
        query.append("hinweis=normalisierung")
    suffix = f"?{'&'.join(query)}" if query else ""
    return RedirectResponse(f"/admin/concepts{suffix}#concept-{concept_id}", status_code=303)


@router.get("/concepts")
def concepts_page(
    request: Request,
    _: AdminDependency,
    db: DbDependency,
    kind: Annotated[str | None, Query()] = None,
    hinweis: Annotated[str | None, Query()] = None,
):
    profile = _profile_or_503(db)
    selected_kind = _kind_or_none(kind)
    rows = list_concepts_for_admin(db, profile, kind=selected_kind)
    return templates.TemplateResponse(
        request=request,
        name="admin_concepts.html",
        context={
            "profile": profile,
            "rows": rows,
            "kinds": list(ConceptKind),
            "kind_labels": KIND_LABELS,
            "kind_labels_by_value": KIND_LABELS_BY_VALUE,
            "selected_kind": selected_kind,
            "state_labels": STATE_LABELS,
            "preference_states": list(CandidatePreferenceState),
            "normalization_notice": hinweis == "normalisierung",
        },
    )


@router.post("/concepts/{concept_id}/preference")
def set_preference(
    concept_id: int,
    _: AdminDependency,
    db: DbDependency,
    state_value: Annotated[str, Form(alias="state")],
    return_kind: Annotated[str, Form()] = "",
):
    profile = _profile_or_503(db)
    try:
        preference_state = CandidatePreferenceState(state_value)
        set_manual_preference(db, profile, concept_id, preference_state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Ungültiger Bewertungszustand.") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Konzept nicht gefunden.") from exc
    return _redirect(concept_id, kind=return_kind)


@router.post("/concepts/{concept_id}/preference/reset")
def reset_preference(
    concept_id: int,
    _: AdminDependency,
    db: DbDependency,
    return_kind: Annotated[str, Form()] = "",
):
    profile = _profile_or_503(db)
    try:
        reset_preference_to_seed(db, profile, concept_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Konzept nicht gefunden.") from exc
    return _redirect(concept_id, kind=return_kind)


@router.post("/concepts/{concept_id}/aliases")
def add_alias(
    concept_id: int,
    _: AdminDependency,
    db: DbDependency,
    alias: Annotated[str, Form()],
    language: Annotated[str, Form()] = "",
    return_kind: Annotated[str, Form()] = "",
):
    try:
        add_manual_alias(db, concept_id, alias, language=language or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Alias darf nicht leer sein.") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Konzept nicht gefunden.") from exc
    return _redirect(concept_id, kind=return_kind, aliases_changed=True)


@router.post("/aliases/{alias_id}/toggle")
def toggle_alias(
    alias_id: int,
    _: AdminDependency,
    db: DbDependency,
    concept_id: Annotated[int, Form()],
    enabled: Annotated[str, Form()],
    return_kind: Annotated[str, Form()] = "",
):
    try:
        set_alias_enabled(db, alias_id, enabled=enabled == "1")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Alias nicht gefunden.") from exc
    return _redirect(concept_id, kind=return_kind, aliases_changed=True)


@router.post("/aliases/{alias_id}/delete")
def remove_alias(
    alias_id: int,
    _: AdminDependency,
    db: DbDependency,
    concept_id: Annotated[int, Form()],
    return_kind: Annotated[str, Form()] = "",
):
    try:
        delete_manual_alias(db, alias_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Alias nicht gefunden.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Standard-Synonyme können nur deaktiviert werden.") from exc
    return _redirect(concept_id, kind=return_kind, aliases_changed=True)
