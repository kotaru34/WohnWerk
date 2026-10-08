from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from geoalchemy2 import Geography, Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, cast, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.config import get_settings
from app.country_scope import selected_country
from app.database import Base
from app.jobs.location_resolution import AUSTRIAN_POSTAL_SOURCE
from app.models import PostalCode, Property
from app.postal_codes_de import GEONAMES_SOURCE
from app.property_location_filter import PropertyFilterCenter, resolve_property_filter_center
from app.routing import OSRMClient, RoutingError, RoutingPoint
from app.workplace_geocoding import (
    geocode_german_workplace,
    parse_german_street_address,
)

_SUPPORTED_COUNTRIES = {"AT", "DE"}
_POSTAL_PATTERNS = {
    "AT": re.compile(r"(?<!\d)(\d{4})(?!\d)"),
    "DE": re.compile(r"(?<!\d)(\d{5})(?!\d)"),
}
_POSTAL_SOURCES = {
    "AT": AUSTRIAN_POSTAL_SOURCE,
    "DE": GEONAMES_SOURCE,
}


class CandidateWorkplace(Base):
    """One explicit workplace setting for one candidate profile.

    The entered text is always preserved. Coordinates are stored only after a
    defensible country-scoped PLZ/locality resolution; street-level precision is
    never claimed when the evidence is only a postal/locality centroid.
    """

    __tablename__ = "candidate_workplaces"
    __table_args__ = (Index("ix_candidate_workplaces_profile_id", "profile_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    input_text: Mapped[str] = mapped_column(String(500), nullable=False)
    postal_code: Mapped[str | None] = mapped_column(String(5))
    city: Mapped[str | None] = mapped_column(String(160))
    location: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True)
    )
    resolution_source: Mapped[str | None] = mapped_column(String(160))
    resolution_method: Mapped[str | None] = mapped_column(String(80))
    resolution_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


@dataclass(frozen=True, slots=True)
class WorkplaceResolution:
    country_code: str
    input_text: str
    postal_code: str | None
    city: str | None
    center: PropertyFilterCenter | None
    source: str | None
    method: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class WorkplaceDistance:
    property_id: int
    air_distance_km: float
    road_distance_km: float | None = None
    road_duration_minutes: float | None = None


def normalize_workplace_country(country_code: str) -> str:
    normalized = country_code.strip().upper()
    if normalized not in _SUPPORTED_COUNTRIES:
        raise ValueError("Arbeitsplatz-Land muss AT oder DE sein.")
    return normalized


def extract_explicit_postal_code(country_code: str, value: str) -> str | None:
    country = normalize_workplace_country(country_code)
    matches = tuple(dict.fromkeys(_POSTAL_PATTERNS[country].findall(value)))
    if len(matches) > 1:
        raise ValueError("Arbeitsplatz enthält mehrere unterschiedliche PLZ.")
    return matches[0] if matches else None


def _postal_city(
    session: Session,
    *,
    country_code: str,
    postal_code: str,
) -> str | None:
    source = _POSTAL_SOURCES[country_code]
    return session.scalar(
        select(PostalCode.name)
        .where(
            PostalCode.postal_code == postal_code,
            PostalCode.source == source,
        )
        .limit(1)
    )


def resolve_candidate_workplace(
    session: Session,
    *,
    country_code: str,
    input_text: str,
) -> WorkplaceResolution:
    country = normalize_workplace_country(country_code)
    text = " ".join(input_text.strip().split())
    if not text:
        raise ValueError("Arbeitsplatz darf nicht leer sein.")

    postal_code = extract_explicit_postal_code(country, text)
    query = postal_code or text
    center = resolve_property_filter_center(
        session,
        query,
        country_code=country,
    )
    if center is None:
        return WorkplaceResolution(
            country_code=country,
            input_text=text,
            postal_code=postal_code,
            city=None,
            center=None,
            source=None,
            method=None,
            error=(
                f"Arbeitsplatz „{text}“ konnte für {country} nicht belastbar "
                "aufgelöst werden."
            ),
        )

    source = _POSTAL_SOURCES[country]
    if postal_code is not None:
        city = _postal_city(session, country_code=country, postal_code=postal_code)
        method = "explicit_postal_centroid"
    else:
        city = text
        method = "locality_centroid"

    # A PLZ centroid is not an address coordinate. Exact address lookup is
    # manually opt-in, single-request and never applied to scraped listings.
    settings = get_settings()
    if country == "DE" and settings.workplace_geocoding_enabled and postal_code:
        street = parse_german_street_address(text)
        if street is not None and street.postal_code == postal_code:
            precise_center = geocode_german_workplace(
                street,
                postal_centroid=center,
                base_url=settings.workplace_geocoding_base_url,
                user_agent=settings.workplace_geocoding_user_agent,
                timeout_seconds=settings.workplace_geocoding_timeout_seconds,
                max_centroid_distance_km=settings.workplace_geocoding_max_postal_centroid_km,
            )
            if precise_center is not None:
                center = precise_center
                source = "OpenStreetMap/Nominatim"
                method = "verified_street_address"
            else:
                # Cache a failed attempt: do not repeatedly query a public
                # geocoder for an unchanged address on unrelated settings saves.
                method = "street_address_unverified"

    return WorkplaceResolution(
        country_code=country,
        input_text=text,
        postal_code=postal_code,
        city=city,
        center=center,
        source=source,
        method=method,
        error=None,
    )


def load_candidate_workplace(
    session: Session,
    profile_id: int,
) -> CandidateWorkplace | None:
    return session.scalar(
        select(CandidateWorkplace).where(CandidateWorkplace.profile_id == profile_id)
    )


def save_candidate_workplace(
    session: Session,
    profile_id: int,
    *,
    country_code: str,
    input_text: str,
    commit: bool = True,
) -> CandidateWorkplace | None:
    text = input_text.strip()
    row = load_candidate_workplace(session, profile_id)
    if not text:
        if row is not None:
            session.delete(row)
            if commit:
                session.commit()
        return None

    # Settings forms can be saved many times without changing the workplace.
    # Reuse cached address evidence; allow one legacy PLZ-centroid upgrade when
    # an operator subsequently enables the address-geocoding integration.
    normalized_country = normalize_workplace_country(country_code)
    normalized_text = " ".join(text.split())
    if (
        row is not None
        and row.country_code == normalized_country
        and row.input_text == normalized_text
        and not (
            normalized_country == "DE"
            and get_settings().workplace_geocoding_enabled
            and row.resolution_method == "explicit_postal_centroid"
            and parse_german_street_address(normalized_text) is not None
        )
    ):
        return row

    resolution = resolve_candidate_workplace(
        session,
        country_code=normalized_country,
        input_text=normalized_text,
    )
    if row is None:
        row = CandidateWorkplace(
            profile_id=profile_id,
            country_code=resolution.country_code,
            input_text=resolution.input_text,
        )
        session.add(row)

    row.country_code = resolution.country_code
    row.input_text = resolution.input_text
    row.postal_code = resolution.postal_code
    row.city = resolution.city
    row.resolution_source = resolution.source
    row.resolution_method = resolution.method
    row.resolution_error = resolution.error
    row.location = (
        WKTElement(
            f"POINT({resolution.center.longitude:.8f} {resolution.center.latitude:.8f})",
            srid=4326,
        )
        if resolution.center is not None
        else None
    )
    if commit:
        session.commit()
    return row


def workplace_distance_stmt(profile_id: int, property_ids: set[int]):
    distance_km = (
        func.ST_Distance(Property.location, CandidateWorkplace.location) / 1000.0
    ).label("air_distance_km")
    return (
        select(Property.id.label("property_id"), distance_km)
        .select_from(Property)
        .join(CandidateWorkplace, CandidateWorkplace.profile_id == profile_id)
        .where(
            Property.id.in_(property_ids),
            Property.location.is_not(None),
            CandidateWorkplace.location.is_not(None),
        )
    )


def _workplace_routing_point(
    session: Session,
    profile_id: int,
) -> RoutingPoint | None:
    geometry = cast(
        CandidateWorkplace.location,
        Geometry(geometry_type="POINT", srid=4326),
    )
    row = session.execute(
        select(
            func.ST_X(geometry).label("longitude"),
            func.ST_Y(geometry).label("latitude"),
        ).where(
            CandidateWorkplace.profile_id == profile_id,
            CandidateWorkplace.location.is_not(None),
        )
    ).one_or_none()
    if row is None or row.longitude is None or row.latitude is None:
        return None
    return RoutingPoint(
        longitude=float(row.longitude),
        latitude=float(row.latitude),
    )


def _property_routing_points(
    session: Session,
    property_ids: set[int],
) -> dict[int, RoutingPoint]:
    if not property_ids:
        return {}
    geometry = cast(Property.location, Geometry(geometry_type="POINT", srid=4326))
    rows = session.execute(
        select(
            Property.id,
            func.ST_X(geometry).label("longitude"),
            func.ST_Y(geometry).label("latitude"),
        ).where(
            Property.id.in_(property_ids),
            Property.location.is_not(None),
        )
    )
    return {
        int(row.id): RoutingPoint(
            longitude=float(row.longitude),
            latitude=float(row.latitude),
        )
        for row in rows
        if row.longitude is not None and row.latitude is not None
    }


def load_workplace_distances(
    session: Session,
    profile_id: int,
    property_ids: set[int],
    *,
    router: OSRMClient | None = None,
) -> dict[int, WorkplaceDistance]:
    if not property_ids:
        return {}

    air_rows = session.execute(workplace_distance_stmt(profile_id, property_ids))
    output = {
        int(row.property_id): WorkplaceDistance(
            property_id=int(row.property_id),
            air_distance_km=float(row.air_distance_km),
        )
        for row in air_rows
        if row.air_distance_km is not None
    }
    if router is None or not output:
        return output

    origin = _workplace_routing_point(session, profile_id)
    property_points = _property_routing_points(session, set(output))
    if origin is None or not property_points:
        return output

    ordered_ids = [property_id for property_id in output if property_id in property_points]
    points = [property_points[property_id] for property_id in ordered_ids]
    try:
        estimates = router.table(origin, points)
    except RoutingError:
        return output

    for property_id, estimate in zip(ordered_ids, estimates, strict=True):
        if not estimate.reachable:
            continue
        air = output[property_id]
        output[property_id] = WorkplaceDistance(
            property_id=property_id,
            air_distance_km=air.air_distance_km,
            road_distance_km=estimate.distance_km,
            road_duration_minutes=estimate.duration_minutes,
        )
    return output


def routing_graph_supports(country: str | None, configured_countries: str) -> bool:
    """Allow routing only for countries explicitly verified in the loaded graph."""
    return bool(country) and country.strip().upper() in {
        part.strip().upper() for part in configured_countries.split(",") if part.strip()
    }


def load_workplace_distances_for_ui(
    session: Session,
    profile_id: int,
    property_ids: set[int],
) -> dict[int, WorkplaceDistance]:
    settings = get_settings()
    workplace = load_candidate_workplace(session, profile_id)
    property_country = selected_country() or settings.country_code
    # This installation searches German houses and commutes to a German workplace.
    # Unknown/mismatched router coverage must never yield a fabricated road distance.
    if (
        not settings.routing_enabled
        or workplace is None
        or not routing_graph_supports(workplace.country_code, settings.routing_graph_countries)
        or not routing_graph_supports(property_country, settings.routing_graph_countries)
    ):
        return load_workplace_distances(session, profile_id, property_ids)

    with OSRMClient(
        settings.routing_base_url,
        timeout_seconds=settings.routing_timeout_seconds,
        max_table_coordinates=settings.routing_max_table_coordinates,
        max_snap_distance_metres=settings.routing_max_snap_distance_metres,
    ) as client:
        return load_workplace_distances(
            session,
            profile_id,
            property_ids,
            router=client,
        )
