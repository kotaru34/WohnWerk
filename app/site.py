from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, status
from fastapi.responses import RedirectResponse

from app.admin import (
    JOB_FILTERS,
    AdminDependency,
    CsrfDependency,
    DbDependency,
    jobs_page,
)
from app.jobs.candidate_job_store import set_job_favorite, set_job_hidden
from app.jobs.candidate_profile_store import get_seed_profile
from app.matches import matches_page

router = APIRouter(tags=["site"])

router.add_api_route("/matches", matches_page, methods=["GET"], include_in_schema=False)
router.add_api_route("/jobs", jobs_page, methods=["GET"], include_in_schema=False)

_JOB_SORTS = {"passung", "gehalt", "neuheit", "gesehen"}
_SORT_DIRECTIONS = {"asc", "desc"}


def _profile_or_503(db: DbDependency):
    profile = get_seed_profile(db)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Kandidatenprofil ist noch nicht initialisiert.",
        )
    return profile


def _job_redirect(
    job_id: int,
    *,
    view: str,
    search: str,
    sort: str | None = None,
    direction: str | None = None,
) -> RedirectResponse:
    query = {"ansicht": view}
    if sort:
        query["sortierung"] = sort
    if direction:
        query["richtung"] = direction
    if search.strip():
        query["suche"] = search.strip()
    return RedirectResponse(f"/jobs?{urlencode(query)}#job-{job_id}", status_code=303)


def _valid_return_view(value: str) -> str:
    return value if value in JOB_FILTERS or value == "neu" else "passend"


def _valid_return_sort(value: str) -> str | None:
    return value if value in _JOB_SORTS else None


def _valid_return_direction(value: str) -> str | None:
    return value if value in _SORT_DIRECTIONS else None


@router.post("/jobs/{job_id}/favorite", include_in_schema=False)
def update_job_favorite(
    job_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    favorite: Annotated[str, Form()],
    return_view: Annotated[str, Form()] = "passend",
    return_search: Annotated[str, Form()] = "",
    return_sort: Annotated[str, Form()] = "",
    return_direction: Annotated[str, Form()] = "",
):
    profile = _profile_or_503(db)
    return_view = _valid_return_view(return_view)
    try:
        set_job_favorite(db, profile, job_id, favorite=favorite == "1")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Stelle nicht gefunden.") from exc
    return _job_redirect(
        job_id,
        view=return_view,
        search=return_search,
        sort=_valid_return_sort(return_sort),
        direction=_valid_return_direction(return_direction),
    )


@router.post("/jobs/{job_id}/hidden", include_in_schema=False)
def update_job_hidden(
    job_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    hidden: Annotated[str, Form()],
    return_view: Annotated[str, Form()] = "passend",
    return_search: Annotated[str, Form()] = "",
    return_sort: Annotated[str, Form()] = "",
    return_direction: Annotated[str, Form()] = "",
):
    profile = _profile_or_503(db)
    return_view = _valid_return_view(return_view)
    try:
        set_job_hidden(db, profile, job_id, hidden=hidden == "1")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Stelle nicht gefunden.") from exc
    return _job_redirect(
        job_id,
        view=return_view,
        search=return_search,
        sort=_valid_return_sort(return_sort),
        direction=_valid_return_direction(return_direction),
    )
