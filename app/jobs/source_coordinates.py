from __future__ import annotations

import math

from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JobListing, JobLocation, ListingStatus


def apply_source_job_coordinates(session: Session, source_id: int) -> int:
    """Use explicit source WGS84 coordinates for still-unresolved job locations.

    This is intentionally a fallback: PLZ/locality resolution remains authoritative.
    A source coordinate is only copied when WohnWerk has no location point yet.
    """
    rows = session.execute(
        select(JobListing, JobLocation)
        .join(JobLocation, JobLocation.job_id == JobListing.job_id)
        .where(
            JobListing.source_id == source_id,
            JobListing.status == ListingStatus.ACTIVE,
            JobLocation.location.is_(None),
        )
    )
    updated = 0
    for listing, location in rows:
        payload = listing.raw_payload or {}
        try:
            latitude = float(payload.get("latitude"))
            longitude = float(payload.get("longitude"))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(latitude) and math.isfinite(longitude)):
            continue
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue
        location.location = WKTElement(
            f"POINT({longitude:.8f} {latitude:.8f})",
            srid=4326,
        )
        updated += 1

    if updated:
        session.commit()
    return updated
