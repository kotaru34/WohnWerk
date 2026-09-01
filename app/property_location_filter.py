from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from geoalchemy2 import Geography, Geometry
from sqlalchemy import and_, cast, false, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.geo import radius_metres
from app.house_filters import HouseFilters
from app.jobs.location_resolution import resolve_locality
from app.models import PostalCode, Property

_POSTAL_CODE_RE = re.compile(r"^\d{4}$")
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


def _postal_center(session: Session, postal_code: str) -> PropertyFilterCenter | None:
    geometry = cast(PostalCode.location, _POINT_GEOMETRY)
    row = session.execute(
        select(
            func.ST_X(geometry).label("longitude"),
            func.ST_Y(geometry).label("latitude"),
        )
        .where(
            PostalCode.postal_code == postal_code,
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


def resolve_property_filter_center(
    session: Session,
    value: str,
) -> PropertyFilterCenter | None:
    query = value.strip()
    if not query:
        return None

    if _POSTAL_CODE_RE.fullmatch(query):
        postal = _postal_center(session, query)
        if postal is not None:
            return postal

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
