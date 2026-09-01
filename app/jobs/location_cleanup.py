from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import JobLocation

_COUNTRY_CODE_CITIES = {"at", "aut"}


def is_redundant_country_code_location(
    location: JobLocation,
    siblings: list[JobLocation],
) -> bool:
    """Return true only for a non-point country-code artifact with a concrete sibling.

    Countrywide remote scopes are meaningful source data and must survive. Likewise, an
    unresolved country-code row is retained when it is the only location evidence for a
    job. We only remove the artifact when the same canonical job already has another
    source-backed point/PLZ location.
    """
    city = (location.city or "").strip().casefold()
    if city not in _COUNTRY_CODE_CITIES:
        return False
    if location.remote or location.postal_code is not None or location.location is not None:
        return False

    return any(
        sibling.id != location.id
        and (sibling.location is not None or sibling.postal_code is not None)
        for sibling in siblings
    )


def prune_redundant_country_code_locations(session: Session) -> int:
    candidates = list(
        session.scalars(
            select(JobLocation)
            .where(
                JobLocation.location.is_(None),
                JobLocation.postal_code.is_(None),
                JobLocation.remote.is_(False),
                func.lower(JobLocation.city).in_(_COUNTRY_CODE_CITIES),
            )
            .order_by(JobLocation.job_id, JobLocation.id)
        )
    )
    if not candidates:
        return 0

    job_ids = {location.job_id for location in candidates}
    rows_by_job: dict[int, list[JobLocation]] = {}
    for row in session.scalars(
        select(JobLocation)
        .where(JobLocation.job_id.in_(job_ids))
        .order_by(JobLocation.job_id, JobLocation.id)
    ):
        rows_by_job.setdefault(row.job_id, []).append(row)

    removed = 0
    for location in candidates:
        siblings = rows_by_job.get(location.job_id, [])
        if not is_redundant_country_code_location(location, siblings):
            continue
        session.delete(location)
        removed += 1

    return removed
