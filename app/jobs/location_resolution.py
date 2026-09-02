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
MULTI_LOCALITY_LOCATION_METHOD = "multi_locality_equal_centroid"
DIRECTIONAL_ANCHOR_LOCATION_METHOD = "directional_anchor_locality_centroid"
AREA_ANCHOR_LOCATION_METHOD = "area_anchor_locality_centroid"
NAMED_REGION_LOCATION_METHOD = "named_region_multi_locality_centroid"

_LOCALITY_ALIASES = {
    "vienna": "wien",
    "vienna austria": "wien",
    "wien austria": "wien",
    "graz austria": "graz",
    "linz austria": "linz",
    "salzburg austria": "salzburg",
    "innsbruck austria": "innsbruck",
    "klagenfurt": "klagenfurt am wörthersee",
    "klagenfurt austria": "klagenfurt am wörthersee",
    "klagenfurt am worthersee": "klagenfurt am wörthersee",
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

# Bundesland / macro-region labels are useful as human-readable source data, but they are
# not point locations. In particular, never turn "Kärnten" or "Österreich" into an
# invented centre point merely to make radius search return something.
_NON_POINT_REGIONS = {
    "burgenland",
    "kärnten",
    "kaernten",
    "niederösterreich",
    "niederoesterreich",
    "oberösterreich",
    "oberoesterreich",
    "steiermark",
    "tirol",
    "vorarlberg",
    "ostösterreich",
    "ostoesterreich",
    "westösterreich",
    "westoesterreich",
    "südösterreich",
    "suedoesterreich",
}

# Source-backed scopes that are meaningful for display/filtering but deliberately do not
# identify one point. Keep this list narrow: e.g. `Salzburg Umgebung` has an explicit city
# anchor and remains resolvable through AREA_ANCHOR_LOCATION_METHOD.
_NON_POINT_OPERATIONAL_SCOPES = {
    "österreichweit",
    "oesterreichweit",
    "austriawide",
    "austria wide",
    "wels land",
    "graz umgebung west",
}

# A few source phrases have a stable, well-understood regional meaning that can be
# represented more honestly by several named city centroids than by one arbitrary point.
# This is deliberately a tiny allow-list rather than a generic Bundesland-centre feature.
_NAMED_REGION_LOCALITIES = {
    "oberösterreich zentralraum": ("linz", "wels", "steyr"),
    "oberoesterreich zentralraum": ("linz", "wels", "steyr"),
    "zentralraum oberösterreich": ("linz", "wels", "steyr"),
    "zentralraum oberoesterreich": ("linz", "wels", "steyr"),
}

_NON_WORD_RE = re.compile(r"[^\wäöüß]+", flags=re.UNICODE)
_DISTRICT_SCOPE_RE = re.compile(r"^bezirk\s+", flags=re.IGNORECASE)
_AREA_PREFIX_RE = re.compile(r"^\s*(?:großraum|grossraum)\s+", flags=re.IGNORECASE)
_COUNTRY_SUFFIX_RE = re.compile(
    r"(?:\s*,\s*|\s+)(?:austria|österreich)\s*$",
    flags=re.IGNORECASE,
)
_AREA_SEPARATOR_RE = re.compile(r"\s*[,;/]\s*")
_DIRECTIONAL_ANCHOR_RE = re.compile(
    r"^\s*(?:nördlich|noerdlich|südlich|suedlich|östlich|oestlich|westlich)\s+von\s+(.+?)\s*$",
    flags=re.IGNORECASE,
)
_AREA_AROUND_ANCHOR_RE = re.compile(
    r"^\s*(?:raum\s+)?(?P<anchor>.+?)\s+(?:und\s+)?umgebung\s*$",
    flags=re.IGNORECASE,
)
_RAUM_ANCHOR_RE = re.compile(
    r"^\s*raum\s+(?P<anchor>.+?)\s*$",
    flags=re.IGNORECASE,
)


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


def is_non_point_location_scope(value: str | None) -> bool:
    """Return whether a source label intentionally describes an area rather than a point.

    This classifier is shared by the resolver and operational UI so a broad regional or
    countrywide scope is not reported as a failed concrete-locality resolution. It is
    intentionally conservative: only explicit country/region/district forms and a tiny set
    of source-backed operational scopes are classified here.
    """
    normalized = _normalized_words(value)
    if not normalized:
        return False
    return (
        normalized in _REMOTE_ONLY
        or normalized in _NON_POINT_REGIONS
        or normalized in _NON_POINT_OPERATIONAL_SCOPES
        or _DISTRICT_SCOPE_RE.match(normalized) is not None
    )


def canonicalize_locality(value: str | None) -> str | None:
    """Normalize a source city label without inventing a more precise location."""
    normalized = _normalized_words(value)
    if not normalized or is_non_point_location_scope(value):
        return None
    return _LOCALITY_ALIASES.get(normalized, normalized)


def directional_anchor_locality(value: str | None) -> str | None:
    """Return the explicit anchor locality from labels such as `Südlich von Wien`.

    The direction itself does not provide a point, so WohnWerk intentionally uses only the
    named anchor locality's centroid and records a distinct resolution method. This is less
    precise than a real Dienstort, but more useful and more honest than treating the entire
    phrase as an unresolvable city or inventing a point south of the anchor.
    """
    if not value:
        return None
    match = _DIRECTIONAL_ANCHOR_RE.match(value)
    if match is None:
        return None
    anchor = _COUNTRY_SUFFIX_RE.sub("", match.group(1)).strip()
    return canonicalize_locality(anchor)


def area_anchor_locality(value: str | None) -> str | None:
    """Extract an explicit city anchor from `Salzburg Umgebung` / `Raum Salzburg`.

    These phrases describe an area, not an exact workplace. Using the named city's centroid
    is nevertheless a useful approximation for radius search, provided provenance remains
    explicit. Pure Bundesland/country labels are rejected by ``canonicalize_locality``.
    """
    if not value:
        return None
    raw = _COUNTRY_SUFFIX_RE.sub("", value.strip()).strip()
    match = _AREA_AROUND_ANCHOR_RE.match(raw) or _RAUM_ANCHOR_RE.match(raw)
    if match is None:
        return None
    return canonicalize_locality(match.group("anchor").strip())


def named_region_localities(value: str | None) -> tuple[str, ...]:
    """Return explicit city anchors for a small allow-list of meaningful named regions."""
    normalized = _normalized_words(_COUNTRY_SUFFIX_RE.sub("", value or ""))
    return _NAMED_REGION_LOCALITIES.get(normalized, ())


def canonicalize_area_localities(value: str | None) -> tuple[str, ...]:
    """Extract explicit localities from conservative `Großraum ...` source labels."""
    if not value:
        return ()

    raw = value.strip()
    if _AREA_PREFIX_RE.match(raw) is None:
        return ()

    body = _AREA_PREFIX_RE.sub("", raw, count=1)
    body = _COUNTRY_SUFFIX_RE.sub("", body).strip()
    if not body:
        return ()

    canonical: list[str] = []
    for part in _AREA_SEPARATOR_RE.split(body):
        locality = canonicalize_locality(part)
        if locality is None:
            return ()
        if locality not in canonical:
            canonical.append(locality)

    # A one-place label is not a multi-locality area and should stay on the normal
    # locality path rather than acquiring an area-resolution provenance label.
    if len(canonical) < 2:
        return ()
    return tuple(canonical)


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


def combine_locality_resolutions(
    requested_city: str,
    resolutions: list[LocalityResolution],
    *,
    method: str = MULTI_LOCALITY_LOCATION_METHOD,
) -> LocalityResolution | None:
    """Represent an explicit multi-locality area by the mean of locality centroids."""
    if len(resolutions) < 2:
        return None

    count = len(resolutions)
    longitude = sum(item.longitude for item in resolutions) / count
    latitude = sum(item.latitude for item in resolutions) / count
    canonical_locality = " | ".join(item.canonical_locality for item in resolutions)

    return LocalityResolution(
        requested_city=requested_city,
        canonical_locality=canonical_locality,
        longitude=longitude,
        latitude=latitude,
        postal_codes=tuple(
            sorted({postal for item in resolutions for postal in item.postal_codes})
        ),
        address_sample_count=sum(item.address_sample_count for item in resolutions),
        method=method,
    )


def _resolve_component_area(
    session: Session,
    requested_city: str,
    localities: tuple[str, ...],
    *,
    method: str,
) -> LocalityResolution | None:
    component_resolutions: list[LocalityResolution] = []
    for locality in localities:
        component = resolve_locality(session, locality)
        if component is None:
            # Do not silently approximate an area while dropping one of the explicitly
            # selected anchors.
            return None
        component_resolutions.append(component)
    return combine_locality_resolutions(
        requested_city,
        component_resolutions,
        method=method,
    )


def resolve_locality(session: Session, city: str | None) -> LocalityResolution | None:
    if city is None:
        return None

    directional_anchor = directional_anchor_locality(city)
    if directional_anchor is not None:
        anchor_resolution = resolve_locality(session, directional_anchor)
        if anchor_resolution is None:
            return None
        return LocalityResolution(
            requested_city=city,
            canonical_locality=anchor_resolution.canonical_locality,
            longitude=anchor_resolution.longitude,
            latitude=anchor_resolution.latitude,
            postal_codes=anchor_resolution.postal_codes,
            address_sample_count=anchor_resolution.address_sample_count,
            source=anchor_resolution.source,
            method=DIRECTIONAL_ANCHOR_LOCATION_METHOD,
        )

    named_region = named_region_localities(city)
    if named_region:
        return _resolve_component_area(
            session,
            city,
            named_region,
            method=NAMED_REGION_LOCATION_METHOD,
        )

    area_anchor = area_anchor_locality(city)
    if area_anchor is not None:
        anchor_resolution = resolve_locality(session, area_anchor)
        if anchor_resolution is None:
            return None
        return LocalityResolution(
            requested_city=city,
            canonical_locality=anchor_resolution.canonical_locality,
            longitude=anchor_resolution.longitude,
            latitude=anchor_resolution.latitude,
            postal_codes=anchor_resolution.postal_codes,
            address_sample_count=anchor_resolution.address_sample_count,
            source=anchor_resolution.source,
            method=AREA_ANCHOR_LOCATION_METHOD,
        )

    area_localities = canonicalize_area_localities(city)
    if area_localities:
        return _resolve_component_area(
            session,
            city,
            area_localities,
            method=MULTI_LOCALITY_LOCATION_METHOD,
        )

    canonical = canonicalize_locality(city)
    if canonical is None:
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
