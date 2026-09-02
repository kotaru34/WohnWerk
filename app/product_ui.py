from __future__ import annotations

import math
from collections.abc import Callable
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import exists, func, select

from app.admin import AdminDependency, DbDependency, _csrf_token
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
from app.jobs.candidate_profile_store import get_seed_profile
from app.jobs.fit_store import JobFitView, annual_salary_label, load_live_job_fit
from app.models import Job, Property
from app.property_acquisition import PROPERTY_MAX_PRICE_EUR, PROPERTY_MIN_PRICE_EUR
from app.property_location_filter import resolve_property_radius_filter
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
HOUSE_SORTS = {
    "neuheit": "Neuheit",
    "preis": "Preis",
    "gesehen": "Gesehen",
}
JOB_SORTS = {
    "passung": "Passung",
    "gehalt": "Gehalt",
    "neuheit": "Neuheit",
    "gesehen": "Gesehen",
}
SORT_DIRECTIONS = {"asc", "desc"}


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


def _validated_sort(value: str, choices: dict[str, str], *, default: str) -> str:
    return value if value in choices else default


def _validated_direction(value: str, *, default: str = "desc") -> str:
    return value if value in SORT_DIRECTIONS else default


def _house_order_by(profile_id: int, sort: str, direction: str):
    viewed = exists(
        select(CandidatePropertyPreference.id).where(
            CandidatePropertyPreference.profile_id == profile_id,
            CandidatePropertyPreference.property_id == Property.id,
            CandidatePropertyPreference.viewed_at.is_not(None),
        )
    )
    expression = {
        "preis": Property.price_eur,
        "gesehen": viewed,
        "neuheit": Property.first_seen_at,
    }[sort]
    primary = expression.asc() if direction == "asc" else expression.desc()
    if sort == "preis":
        primary = primary.nullslast()
    tie = Property.id.asc() if direction == "asc" else Property.id.desc()
    return primary, tie


def _job_salary_sort_value(job: Job) -> Decimal | None:
    """Return a conservative EUR/year comparison key without persisting an estimate."""
    if job.salary_min_eur_year is not None:
        return job.salary_min_eur_year
    if job.salary_max_eur_year is not None:
        return job.salary_max_eur_year
    if (job.salary_currency or "").upper() != "EUR":
        return None
    amount = job.salary_min if job.salary_min is not None else job.salary_max
    if amount is None:
        return None
    period = (job.salary_period or "").lower()
    if period == "year":
        return amount
    if period == "month":
        # Unknown Austrian payment count is deliberately not written as annual salary.
        # For sorting only, 12x is a conservative lower-bound comparison key.
        return amount * Decimal(job.salary_payment_count or 12)
    return None


def _job_fit_sort_value(row: JobFitView) -> int | None:
    if row.result.hard_constraints:
        return -1
    return row.result.score


def _sort_rows_missing_last(
    rows: list[JobFitView],
    key: Callable[[JobFitView], Any | None],
    *,
    descending: bool,
) -> list[JobFitView]:
    known: list[tuple[Any, JobFitView]] = []
    missing: list[JobFitView] = []
    for row in rows:
        value = key(row)
        if value is None:
            missing.append(row)
        else:
            known.append((value, row))
    known.sort(
        key=lambda item: (item[0], item[1].job.id),
        reverse=descending,
    )
    missing.sort(key=lambda row: row.job.id, reverse=descending)
    return [row for _value, row in known] + missing


def _sort_job_rows(
    rows: list[JobFitView],
    *,
    sort: str,
    direction: str,
) -> list[JobFitView]:
    descending = direction == "desc"
    if sort == "passung":
        return _sort_rows_missing_last(rows, _job_fit_sort_value, descending=descending)
    if sort == "gehalt":
        return _sort_rows_missing_last(
            rows,
            lambda row: _job_salary_sort_value(row.job),
            descending=descending,
        )
    if sort == "neuheit":
        return sorted(
            rows,
            key=lambda row: (row.job.first_seen_at, row.job.id),
            reverse=descending,
        )
    return sorted(
        rows,
        key=lambda row: (row.viewed, row.job.id),
        reverse=descending,
    )


@router.get("/houses", include_in_schema=False)
def houses_page(
    request: Request,
    _: AdminDependency,
    db: DbDependency,
    ort: Annotated[str, Query()] = "",
    radius_km: Annotated[Decimal | None, Query(ge=1, le=250)] = None,
    preis_von: Annotated[Decimal | None, Query(ge=0)] = None,
    preis_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    wohn_von: Annotated[Decimal | None, Query(ge=0)] = None,
    wohn_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    nutz_von: Annotated[Decimal | None, Query(ge=0)] = None,
    nutz_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    grund_von: Annotated[Decimal | None, Query(ge=0)] = None,
    grund_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    ansicht: Annotated[str, Query()] = "alle",
    sortierung: Annotated[str, Query()] = "neuheit",
    richtung: Annotated[str, Query()] = "desc",
    seite: Annotated[int, Query(ge=1)] = 1,
):
    profile = _profile_or_503(db)
    if ansicht not in HOUSE_VIEWS:
        raise HTTPException(status_code=400, detail="Ungültige Häuseransicht.")
    sortierung = _validated_sort(sortierung, HOUSE_SORTS, default="neuheit")
    richtung = _validated_direction(richtung)

    filters = resolve_house_filters(
        request,
        ort=ort,
        radius_km=radius_km,
        preis_von=preis_von,
        preis_bis=preis_bis,
        wohn_von=wohn_von,
        wohn_bis=wohn_bis,
        nutz_von=nutz_von,
        nutz_bis=nutz_bis,
        grund_von=grund_von,
        grund_bis=grund_bis,
    )
    radius_filter = resolve_property_radius_filter(db, filters)
    baseline = novelty_baseline(db, profile)
    curation_view = "alle" if ansicht == "neu" else ansicht
    conditions = [
        *_product_property_conditions(),
        property_curation_condition(profile.id, curation_view),
        *_property_filter_conditions(filters, radius_filter=radius_filter),
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
            .order_by(*_house_order_by(profile.id, sortierung, richtung))
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
            "location_filter_error": radius_filter.error if radius_filter is not None else None,
            "house_views": HOUSE_VIEWS,
            "selected_view": ansicht,
            "house_sorts": HOUSE_SORTS,
            "selected_sort": sortierung,
            "sort_direction": richtung,
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
    sortierung: Annotated[str, Query()] = "passung",
    richtung: Annotated[str, Query()] = "desc",
):
    profile = _profile_for_jobs(db)
    if ansicht not in JOB_FILTERS:
        raise HTTPException(status_code=400, detail="Ungültige Stellenansicht.")
    sortierung = _validated_sort(sortierung, JOB_SORTS, default="passung")
    richtung = _validated_direction(richtung)

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

    result_total = len(rows)
    rows = _sort_job_rows(rows, sort=sortierung, direction=richtung)

    return product_templates.TemplateResponse(
        request=request,
        name="admin_jobs.html",
        context={
            "profile": profile,
            "rows": rows,
            "result_total": result_total,
            "stats": stats,
            "job_filters": JOB_FILTERS,
            "selected_filter": ansicht,
            "job_sorts": JOB_SORTS,
            "selected_sort": sortierung,
            "sort_direction": richtung,
            "search": suche,
            "annual_salary_label": annual_salary_label,
            "csrf_token": _csrf_token(),
        },
    )
