from __future__ import annotations

import re
from dataclasses import dataclass

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.models import PostalCode

LOCALITY_LOCATION_SOURCE = "RTR postal names + BEV postal centroids"
LOCALITY_LOCATION_METHOD = "locality_weighted_postal_centroid"

_LOCALITY_ALIASES = {
    "vienna": "wien",
    "vienna austria": "wien",
    "wien austria": "wien",
    "graz austria": "graz",
    "linz austria": "linz",
    "salzburg austria": "salzburg",
    "innsbruck austria": "innsbruck",
    "klagenfurt austria": "klagenfurt am wörthersee",
}

_REMOTE_ONLY = {
    "austria",
    "österreich",
    "remote",
    "home office",
    "homeoffice",
    "remote austria",
    "home office austria",
}

_NON_WORD_RE = re.compile(r"[^\wäöüß]+", flags=re.UNICODE)


@dataclass(frozen=True, slots=True)
class PostalCentroidCandidate:
    postal_code: str
    name: str
    longitude: float
    latitude: float
    address_sample_count: int


@dataclass(frozen=True, slots=True)
class LocalityResolution:
    requested_city: str
    canonical_locality: str
    longitude: float
    latitude: float
    postal_codes: tuple[str, ...]
    address_sample_count: int
    source: str = LOCALITY_LOCATION_SOURCE
    method: str = LOCALITY_LOCATION_METHOD

    def as_wkt(self) -> WKTElement:
        return WKTElement(f"POINT({self.longitude:.8f} {self.latitude:.8f})", srid=4326)


def _normalized_words(value: str | None) -> str:
    if not value:
        return ""
    normalized = _NON_WORD_RE.sub(" ", value.casefold()).strip()
    return " ".join(normalized.split())


def canonicalize_locality(value: str | None) -> str | None:
    """Normalize a source city label without inventing a more precise location."""
    normalized = _normalized_words(value)
    if not normalized or normalized in _REMOTE_ONLY:
        return None
    return _LOCALITY_ALIASES.get(normalized, normalized)


def locality_name_matches(postal_name: str, canonical_locality: str) -> bool:
    """Match RTR locality names conservatively, avoiding Wien -> Wiener Neustadt."""
    candidate = _normalized_words(postal_name)
    target = _normalized_words(canonical_locality)
    if not candidate or not target:
        return False
    if candidate == target:
        return True
    return candidate.startswith(f"{target} ")


def combine_postal_centroids(
    requested_city: str,
    canonical_locality: str,
    candidates: list[PostalCentroidCandidate],
) -> LocalityResolution | None:
    """Build an approximate locality point weighted by BEV address samples."""
    matched = [
        item for item in candidates if locality_name_matches(item.name, canonical_locality)
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
        requested_city=requested_city,
        canonical_locality=canonical_locality,
        longitude=longitude,
        latitude=latitude,
        postal_codes=tuple(sorted({item.postal_code for item in matched})),
        address_sample_count=sum(max(0, item.address_sample_count) for item in matched),
    )


def resolve_locality(session: Session, city: str | None) -> LocalityResolution | None:
    canonical = canonicalize_locality(city)
    if canonical is None or city is None:
        return None

    geometry = cast(PostalCode.location, Geometry(geometry_type="POINT", srid=4326))
    rows = session.execute(
        select(
            PostalCode.postal_code,
            PostalCode.name,
            func.ST_X(geometry),
            func.ST_Y(geometry),
            PostalCode.location_sample_count,
        ).where(
            PostalCode.location.is_not(None),
            func.lower(PostalCode.name).like(f"{canonical.casefold()}%"),
        )
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

    return combine_postal_centroids(city, canonical, candidates)


def resolve_localities(
    session: Session,
    cities: set[str],
) -> dict[str, LocalityResolution]:
    resolved: dict[str, LocalityResolution] = {}
    for city in sorted(cities):
        resolution = resolve_locality(session, city)
        if resolution is not None:
            resolved[city] = resolution
    return resolved
