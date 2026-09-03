from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from geoalchemy2 import Geography, Geometry
from sqlalchemy import and_, cast, false, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.country_scope import DEFAULT_COUNTRY, selected_country
from app.geo import radius_metres
from app.house_filters import HouseFilters
from app.jobs.location_resolution import AUSTRIAN_POSTAL_SOURCE, resolve_locality
from app.models import PostalCode, Property
from app.postal_codes_de import GEONAMES_SOURCE

_POSTAL_CODE_RE = {
    "AT": re.compile(r"^\d{4}$"),
    "DE": re.compile(r"^\d{5}$"),
}
_POSTAL_SOURCE = {
    "AT": AUSTRIAN_POSTAL_SOURCE,
    "DE": GEONAMES_SOURCE,
}
_POINT_GEOGRAPHY = Geography(geometry_type="POINT", srid=4326)
_POINT_GEOMETRY = Geometry(geometry_type="POINT", srid=4326)


@dataclass(frozen=True, slots=True)
class PropertyFilterCenter:
    longitude: float
    latitude: float


@dataclass(frozen=True, slots=True)
class PropertyRadiusFilter:
    condition: ColumnElement[bool]
    error: str | None = None


def _active_country() -> str:
    return selected_country() or DEFAULT_COUNTRY


def _postal_center(
    session: Session,
    postal_code: str,
    *,
    country_code: str,
) -> PropertyFilterCenter | None:
    geometry = cast(PostalCode.location, _POINT_GEOMETRY)
    source = _POSTAL_SOURCE.get(country_code)
    if source is None:
        return None

    row = session.execute(
        select(
            func.ST_X(geometry).label("longitude"),
            func.ST_Y(geometry).label("latitude"),
        )
        .where(
            PostalCode.postal_code == postal_code,
            PostalCode.source == source,
            PostalCode.location.is_not(None),
        )
        .limit(1)
    ).one_or_none()
    if row is None or row.longitude is None or row.latitude is None:
        return None
    return PropertyFilterCenter(
        longitude=float(row.longitude),
        latitude=float(row.latitude),
    )


def _german_locality_center(session: Session, city: str) -> PropertyFilterCenter | None:
    """Resolve an explicit German locality from GeoNames postal centroids only.

    Several German PLZ rows may share one locality name. Their available GeoNames
    centroids are averaged with the imported sample counts as conservative weights.
    This path deliberately does not reuse the Austria-specific locality aliases or
    fallback heuristics.
    """
    canonical = " ".join(city.strip().casefold().split())
    if not canonical:
        return None

    geometry = cast(PostalCode.location, _POINT_GEOMETRY)
    rows = session.execute(
        select(
            func.ST_X(geometry),
            func.ST_Y(geometry),
            PostalCode.location_sample_count,
        ).where(
            PostalCode.source == GEONAMES_SOURCE,
            PostalCode.location.is_not(None),
            func.lower(PostalCode.name) == canonical,
        )
    )

    samples: list[tuple[float, float, int]] = []
    for longitude, latitude, sample_count in rows:
        if longitude is None or latitude is None:
            continue
        samples.append(
            (
                float(longitude),
                float(latitude),
                max(1, int(sample_count or 0)),
            )
        )
    if not samples:
        return None

    total_weight = sum(weight for _longitude, _latitude, weight in samples)
    return PropertyFilterCenter(
        longitude=sum(longitude * weight for longitude, _latitude, weight in samples)
        / total_weight,
        latitude=sum(latitude * weight for _longitude, latitude, weight in samples)
        / total_weight,
    )


def resolve_property_filter_center(
    session: Session,
    value: str,
) -> PropertyFilterCenter | None:
    query = value.strip()
    if not query:
        return None

    country_code = _active_country()
    postal_pattern = _POSTAL_CODE_RE.get(country_code)
    if postal_pattern is not None and postal_pattern.fullmatch(query):
        postal = _postal_center(session, query, country_code=country_code)
        if postal is not None:
            return postal

    if country_code == "DE":
        return _german_locality_center(session, query)

    locality = resolve_locality(session, query)
    if locality is None:
        return None
    return PropertyFilterCenter(
        longitude=locality.longitude,
        latitude=locality.latitude,
    )


def resolve_property_radius_filter(
    session: Session,
    filters: HouseFilters,
) -> PropertyRadiusFilter | None:
    location = filters.ort.strip()
    radius_km: Decimal | None = filters.radius_km
    if not location or radius_km is None:
        return None

    center = resolve_property_filter_center(session, location)
    if center is None:
        return PropertyRadiusFilter(
            condition=false(),
            error=(
                f"Ort oder PLZ „{location}“ konnte nicht aufgelöst werden. "
                "Der Umkreisfilter zeigt deshalb keine Ergebnisse."
            ),
        )

    center_geometry = func.ST_SetSRID(
        func.ST_MakePoint(center.longitude, center.latitude),
        4326,
    )
    center_geography = cast(center_geometry, _POINT_GEOGRAPHY)
    return PropertyRadiusFilter(
        condition=and_(
            Property.location.is_not(None),
            func.ST_DWithin(
                Property.location,
                center_geography,
                radius_metres(float(radius_km)),
            ),
        )
    )
