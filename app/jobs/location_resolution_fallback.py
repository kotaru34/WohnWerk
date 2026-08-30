from __future__ import annotations

import re

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.jobs.location_resolution import (
    LocalityResolution,
    PostalCentroidCandidate,
    canonicalize_locality,
    combine_postal_centroids,
    locality_name_matches,
)
from app.models import PostalCode

_QUALIFIED_BY_RE = re.compile(r"^(?P<base>.+?)\s+bei\s+.+$", re.IGNORECASE)
_CITY_SUFFIX_RE = re.compile(r"^(?P<base>.+?)\s+stadt$", re.IGNORECASE)
_VIENNA_DISTRICT_RE = re.compile(
    r"^wien\s+\d{1,2}\.?\s*bezirk(?:\s+.*)?$",
    re.IGNORECASE,
)


def _unique_base_resolution(
    city: str,
    base: str,
    candidates: list[PostalCentroidCandidate],
) -> LocalityResolution | None:
    canonical_base = canonicalize_locality(base)
    if canonical_base is None:
        return None
    matched = [
        item for item in candidates if locality_name_matches(item.name, canonical_base)
    ]
    if not matched:
        return None

    # `X bei Y` is only safe to collapse to `X` when the Austrian postal table contains
    # one normalized locality family for that base. Ambiguous bases deliberately remain
    # unresolved instead of guessing between similarly named municipalities.
    normalized_names = {
        canonicalize_locality(item.name)
        for item in matched
        if canonicalize_locality(item.name) is not None
    }
    if len(normalized_names) != 1:
        return None
    return combine_postal_centroids(city, canonical_base, matched)


def resolve_from_candidates(
    city: str,
    candidates: list[PostalCentroidCandidate],
) -> LocalityResolution | None:
    """Resolve one locality against already-loaded postal candidates.

    The normal path reuses the punctuation-normalizing matcher. A very small set of
    conservative source-label fallbacks is attempted afterwards: Vienna district labels,
    `<city> Stadt`, and `X bei Y` only when the postal-table base is unambiguous.
    """
    canonical = canonicalize_locality(city)
    if canonical is None:
        return None

    direct = combine_postal_centroids(city, canonical, candidates)
    if direct is not None:
        return direct

    if _VIENNA_DISTRICT_RE.match(canonical):
        return combine_postal_centroids(city, "wien", candidates)

    city_suffix = _CITY_SUFFIX_RE.match(canonical)
    if city_suffix is not None:
        return combine_postal_centroids(city, city_suffix.group("base"), candidates)

    qualified = _QUALIFIED_BY_RE.match(canonical)
    if qualified is not None:
        return _unique_base_resolution(city, qualified.group("base"), candidates)

    return None


def resolve_localities_full_scan(
    session: Session,
    cities: set[str],
) -> dict[str, LocalityResolution]:
    """Fail-safe locality fallback that scans the small Austrian postal table once.

    The regular resolver keeps its indexed SQL prefix path. Only unresolved localities
    reach this function. No fuzzy matching or invented Bundesland/country centres are
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
