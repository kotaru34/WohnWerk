from __future__ import annotations

import re

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.jobs.location_resolution import (
    LOCALITY_LOCATION_SOURCE,
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
_SANKT_PREFIX_RE = re.compile(r"^sankt\s+", re.IGNORECASE)

OFFICIAL_LOCALITY_POSTAL_METHOD = "statistics_austria_locality_postal_centroid"
VERIFIED_SUBLOCALITY_POSTAL_METHOD = "verified_sublocality_postal_centroid"
VERIFIED_SUBLOCALITY_LOCATION_SOURCE = (
    "verified Austrian sublocality postal membership + BEV postal centroids"
)

# Conservative exception table for real locality/municipality labels which do not map to
# the RTR delivery-place name used by ``PostalCode.name``. Membership comes from current
# Statistics Austria locality/municipality lists; coordinates still come only from the
# locally imported BEV-backed postal centroids. Multi-PLZ localities intentionally keep all
# officially associated postal codes rather than selecting an arbitrary one.
_OFFICIAL_LOCALITY_POSTAL_CODES: dict[str, tuple[str, ...]] = {
    "blaindorf": ("8224", "8265"),
    "ebenthal in kärnten": ("9065",),
    "premstätten": ("8141",),
    "ranshofen": ("5280", "5282"),
    "traboch": ("8770", "8772", "8792"),
}

# A tiny independently verified sublocality/district table. These labels are useful job
# locations but are not necessarily RTR delivery-place names or autonomous municipalities.
# The mapping records only postal membership; the actual point still comes from our local
# BEV-backed postal centroid table. Keep this list evidence-backed and intentionally small.
_VERIFIED_SUBLOCALITY_POSTAL_CODES: dict[str, tuple[str, ...]] = {
    "puntigam": ("8055",),
    "schaftenau": ("6336",),
}


def official_postal_codes_for_locality(city: str) -> tuple[str, ...]:
    canonical = canonicalize_locality(city)
    if canonical is None:
        return ()
    return _OFFICIAL_LOCALITY_POSTAL_CODES.get(canonical, ())


def verified_sublocality_postal_codes(city: str) -> tuple[str, ...]:
    canonical = canonicalize_locality(city)
    if canonical is None:
        return ()
    return _VERIFIED_SUBLOCALITY_POSTAL_CODES.get(canonical, ())


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


def _postal_membership_resolution(
    city: str,
    canonical: str,
    candidates: list[PostalCentroidCandidate],
    *,
    postal_codes: tuple[str, ...],
    source: str,
    method: str,
) -> LocalityResolution | None:
    if not postal_codes:
        return None

    matched = [
        candidate
        for candidate in candidates
        if candidate.postal_code in postal_codes
    ]
    if not matched:
        return None

    total_weight = sum(max(1, item.address_sample_count) for item in matched)
    longitude = sum(
        item.longitude * max(1, item.address_sample_count) for item in matched
    ) / total_weight
    latitude = sum(
        item.latitude * max(1, item.address_sample_count) for item in matched
    ) / total_weight

    return LocalityResolution(
        requested_city=city,
        canonical_locality=canonical,
        longitude=longitude,
        latitude=latitude,
        postal_codes=tuple(sorted({item.postal_code for item in matched})),
        address_sample_count=sum(max(0, item.address_sample_count) for item in matched),
        source=source,
        method=method,
    )


def _official_postal_resolution(
    city: str,
    canonical: str,
    candidates: list[PostalCentroidCandidate],
) -> LocalityResolution | None:
    return _postal_membership_resolution(
        city,
        canonical,
        candidates,
        postal_codes=official_postal_codes_for_locality(city),
        source=LOCALITY_LOCATION_SOURCE,
        method=OFFICIAL_LOCALITY_POSTAL_METHOD,
    )


def _verified_sublocality_resolution(
    city: str,
    canonical: str,
    candidates: list[PostalCentroidCandidate],
) -> LocalityResolution | None:
    return _postal_membership_resolution(
        city,
        canonical,
        candidates,
        postal_codes=verified_sublocality_postal_codes(city),
        source=VERIFIED_SUBLOCALITY_LOCATION_SOURCE,
        method=VERIFIED_SUBLOCALITY_POSTAL_METHOD,
    )


def resolve_from_candidates(
    city: str,
    candidates: list[PostalCentroidCandidate],
) -> LocalityResolution | None:
    """Resolve one locality against already-loaded postal candidates.

    The normal path reuses the punctuation-normalizing matcher. Conservative fallbacks then
    cover punctuation/abbreviation differences, Vienna district labels, `<city> Stadt`,
    `X bei Y`, official locality/postal membership and a tiny verified sublocality table.
    No fuzzy matching or Bundesland/country centre is introduced.
    """
    canonical = canonicalize_locality(city)
    if canonical is None:
        return None

    direct = combine_postal_centroids(city, canonical, candidates)
    if direct is not None:
        return direct

    # Source feeds often spell official Austrian `St.` names as `Sankt`. The full-scan
    # matcher already normalizes punctuation, so converting only the leading word is enough
    # and remains an exact locality-name match afterwards.
    abbreviated_saint = _SANKT_PREFIX_RE.sub("st ", canonical, count=1)
    if abbreviated_saint != canonical:
        saint_resolution = combine_postal_centroids(
            city,
            abbreviated_saint,
            candidates,
        )
        if saint_resolution is not None:
            return saint_resolution

    if _VIENNA_DISTRICT_RE.match(canonical):
        return combine_postal_centroids(city, "wien", candidates)

    city_suffix = _CITY_SUFFIX_RE.match(canonical)
    if city_suffix is not None:
        return combine_postal_centroids(city, city_suffix.group("base"), candidates)

    qualified = _QUALIFIED_BY_RE.match(canonical)
    if qualified is not None:
        qualified_resolution = _unique_base_resolution(
            city,
            qualified.group("base"),
            candidates,
        )
        if qualified_resolution is not None:
            return qualified_resolution

    official = _official_postal_resolution(city, canonical, candidates)
    if official is not None:
        return official

    return _verified_sublocality_resolution(city, canonical, candidates)


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
