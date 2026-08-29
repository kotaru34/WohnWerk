from __future__ import annotations

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.jobs.location_resolution import (
    LocalityResolution,
    PostalCentroidCandidate,
    canonicalize_locality,
    combine_postal_centroids,
)
from app.models import PostalCode


def resolve_from_candidates(
    city: str,
    candidates: list[PostalCentroidCandidate],
) -> LocalityResolution | None:
    """Resolve one locality against already-loaded postal candidates.

    This intentionally reuses the punctuation-normalizing Python matcher from the normal
    resolver. It is a fallback for cases where the SQL prefix prefilter is too literal,
    such as `St. Valentin` becoming canonical `st valentin` before the RTR name is read.
    """
    canonical = canonicalize_locality(city)
    if canonical is None:
        return None
    return combine_postal_centroids(city, canonical, candidates)


def resolve_localities_full_scan(
    session: Session,
    cities: set[str],
) -> dict[str, LocalityResolution]:
    """Fail-safe locality fallback that scans the small Austrian postal table once.

    The regular resolver keeps its indexed SQL prefix path. Only unresolved localities
    reach this function, where matching is done with the same conservative normalized-name
    predicate as the canonical resolver. No fuzzy matching or invented region centres are
    introduced.
    """
    if not cities:
        return {}

    geometry = cast(PostalCode.location, Geometry(geometry_type="POINT", srid=4326))
    rows = session.execute(
        select(
            PostalCode.postal_code,
            PostalCode.name,
            func.ST_X(geometry),
            func.ST_Y(geometry),
            PostalCode.location_sample_count,
        ).where(PostalCode.location.is_not(None))
    )

    candidates: list[PostalCentroidCandidate] = []
    for postal_code, name, longitude, latitude, sample_count in rows:
        if longitude is None or latitude is None:
            continue
        candidates.append(
            PostalCentroidCandidate(
                postal_code=postal_code,
                name=name,
                longitude=float(longitude),
                latitude=float(latitude),
                address_sample_count=int(sample_count or 0),
            )
        )

    resolved: dict[str, LocalityResolution] = {}
    for city in sorted(cities):
        resolution = resolve_from_candidates(city, candidates)
        if resolution is not None:
            resolved[city] = resolution
    return resolved
