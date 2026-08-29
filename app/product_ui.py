from __future__ import annotations

import math
from decimal import Decimal
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import exists, func, select

from app.admin import AdminDependency, CsrfDependency, DbDependency, _csrf_token
from app.candidate_activity import (
    CandidatePropertyPreference,
    novelty_baseline,
    property_curation_condition,
)
from app.catalog import (
    HOUSE_PAGE_SIZE,
    _area_label,
    _eur_label,
    _product_property_conditions,
    _profile_or_503,
    _property_filter_conditions,
    _property_ui_state,
    _property_views,
)
from app.catalog import templates as catalog_templates
from app.house_filters import resolve_house_filters, save_house_filters
from app.jobs.candidate_job_store import set_job_favorite, set_job_hidden
from app.jobs.candidate_profile_store import get_seed_profile
from app.jobs.fit_store import annual_salary_label, load_live_job_fit
from app.models import Property
from app.property_acquisition import PROPERTY_MAX_PRICE_EUR, PROPERTY_MIN_PRICE_EUR
from app.templates_runtime import templates as product_templates

router = APIRouter(tags=["site"])

HOUSE_VIEWS = {
    "alle": "Alle",
    "neu": "Neu",
    "favoriten": "Favoriten",
    "ausgeblendet": "Ausgeblendet",
}
JOB_FILTERS = {
    "passend": "Passend",
    "neu": "Neu",
    "favoriten": "Favoriten",
    "alle": "Alle",
    "unvereinbar": "Unvereinbar",
    "unbewertet": "Unbewertet",
    "ausgeblendet": "Ausgeblendet",
}


def _new_property_condition(profile_id: int, baseline):
    viewed = exists(
        select(CandidatePropertyPreference.id).where(
            CandidatePropertyPreference.profile_id == profile_id,
            CandidatePropertyPreference.property_id == Property.id,
            CandidatePropertyPreference.viewed_at.is_not(None),
        )
    )
    return Property.first_seen_at > baseline, ~viewed


def _profile_for_jobs(db: DbDependency):
    profile = get_seed_profile(db)
    if profile is None:
        raise HTTPException(status_code=503, detail="Kandidatenprofil ist noch nicht initialisiert.")
    return profile


@router.get("/houses", include_in_schema=False)
def houses_page(
    request: Request,
    _: AdminDependency,
    db: DbDependency,
    ort: Annotated[str, Query()] = "",
    preis_von: Annotated[Decimal | None, Query(ge=0)] = None,
    preis_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    wohn_von: Annotated[Decimal | None, Query(ge=0)] = None,
    wohn_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    nutz_von: Annotated[Decimal | None, Query(ge=0)] = None,
    nutz_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    grund_von: Annotated[Decimal | None, Query(ge=0)] = None,
    grund_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    ansicht: Annotated[str, Query()] = "alle",
    seite: Annotated[int, Query(ge=1)] = 1,
):
    profile = _profile_or_503(db)
    if ansicht not in HOUSE_VIEWS:
        raise HTTPException(status_code=400, detail="Ungültige Häuseransicht.")

    filters = resolve_house_filters(
        request,
        ort=ort,
        preis_von=preis_von,
        preis_bis=preis_bis,
        wohn_von=wohn_von,
        wohn_bis=wohn_bis,
        nutz_von=nutz_von,
        nutz_bis=nutz_bis,
        grund_von=grund_von,
        grund_bis=grund_bis,
    )
    baseline = novelty_baseline(db, profile)
    curation_view = "alle" if ansicht == "neu" else ansicht
    conditions = [
        *_product_property_conditions(),
        property_curation_condition(profile.id, curation_view),
        *_property_filter_conditions(filters),
    ]
    if ansicht == "neu":
        conditions.extend(_new_property_condition(profile.id, baseline))

    total = int(db.scalar(select(func.count()).select_from(Property).where(*conditions)) or 0)
    page_count = max(1, math.ceil(total / HOUSE_PAGE_SIZE))
    if seite > page_count and total:
        raise HTTPException(status_code=404, detail="Seite nicht gefunden.")

    rows = list(
        db.scalars(
            select(Property)
            .where(*conditions)
            .order_by(Property.last_seen_at.desc(), Property.id.desc())
            .offset((seite - 1) * HOUSE_PAGE_SIZE)
            .limit(HOUSE_PAGE_SIZE)
        )
    )
    states, new_ids, image_urls = _property_ui_state(db, profile, rows)
    new_conditions = [
        *_product_property_conditions(),
        property_curation_condition(profile.id, "alle"),
        *_new_property_condition(profile.id, baseline),
    ]
    stats = {
        "neu": int(
            db.scalar(select(func.count()).select_from(Property).where(*new_conditions)) or 0
        ),
        "favoriten": int(
            db.scalar(
                select(func.count())
                .select_from(Property)
                .where(
                    *_product_property_conditions(),
                    property_curation_condition(profile.id, "favoriten"),
                )
            )
            or 0
        ),
        "ausgeblendet": int(
            db.scalar(
                select(func.count())
                .select_from(Property)
                .where(
                    *_product_property_conditions(),
                    property_curation_condition(profile.id, "ausgeblendet"),
                )
            )
            or 0
        ),
    }
    response = catalog_templates.TemplateResponse(
        request=request,
        name="houses.html",
        context={
            "rows": _property_views(db, rows),
            "states": states,
            "new_ids": new_ids,
            "image_urls": image_urls,
            "total": total,
            "page": seite,
            "page_count": page_count,
            "filters": filters,
            "house_views": HOUSE_VIEWS,
            "selected_view": ansicht,
            "stats": stats,
            "system_price_min": PROPERTY_MIN_PRICE_EUR,
            "system_price_max": PROPERTY_MAX_PRICE_EUR,
            "eur_label": _eur_label,
            "area_label": _area_label,
            "csrf_token": _csrf_token(),
        },
    )
    save_house_filters(response, filters)
    return response


@router.get("/jobs", include_in_schema=False)
def jobs_page(
    request: Request,
    _: AdminDependency,
    db: DbDependency,
    ansicht: Annotated[str, Query()] = "passend",
    suche: Annotated[str, Query()] = "",
):
    profile = _profile_for_jobs(db)
    if ansicht not in JOB_FILTERS:
        raise HTTPException(status_code=400, detail="Ungültige Stellenansicht.")

    all_rows = load_live_job_fit(db, profile_slug=profile.slug)
    stats = {
        "gesamt": len(all_rows),
        "bewertet": sum(row.result.score is not None for row in all_rows),
        "unvereinbar": sum(bool(row.result.hard_constraints) for row in all_rows),
        "unbewertet": sum(row.result.score is None for row in all_rows),
        "neu": sum(row.is_new and not row.hidden for row in all_rows),
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
    elif ansicht == "neu":
        rows = [row for row in rows if row.is_new and not row.hidden]
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

    return product_templates.TemplateResponse(
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


def _job_redirect(job_id: int, *, view: str, search: str) -> RedirectResponse:
    query = {"ansicht": view if view in JOB_FILTERS else "passend"}
    if search.strip():
        query["suche"] = search.strip()
    return RedirectResponse(f"/jobs?{urlencode(query)}#job-{job_id}", status_code=303)


@router.post("/jobs/{job_id}/favorite", include_in_schema=False)
def update_job_favorite(
    job_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    favorite: Annotated[str, Form()],
    return_view: Annotated[str, Form()] = "passend",
    return_search: Annotated[str, Form()] = "",
):
    profile = _profile_for_jobs(db)
    try:
        set_job_favorite(db, profile, job_id, favorite=favorite == "1")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Stelle nicht gefunden.") from exc
    return _job_redirect(job_id, view=return_view, search=return_search)


@router.post("/jobs/{job_id}/hidden", include_in_schema=False)
def update_job_hidden(
    job_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    hidden: Annotated[str, Form()],
    return_view: Annotated[str, Form()] = "passend",
    return_search: Annotated[str, Form()] = "",
):
    profile = _profile_for_jobs(db)
    try:
        set_job_hidden(db, profile, job_id, hidden=hidden == "1")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Stelle nicht gefunden.") from exc
    return _job_redirect(job_id, view=return_view, search=return_search)
