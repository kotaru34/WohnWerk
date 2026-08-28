from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin import AdminDependency
from app.config import get_settings
from app.database import get_db
from app.jobs.candidate_profile_store import get_seed_profile
from app.jobs.fit_store import JobFitView, annual_salary_label
from app.matching import PropertyDistanceMatch, load_spatial_candidate_matches
from app.models import ListingStatus, PropertyListing, Source
from app.road_matching import load_road_candidate_matches
from app.routing import OSRMClient, RoutingError

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

DbDependency = Annotated[Session, get_db]


@dataclass(frozen=True, slots=True)
class PropertySourceLink:
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class PropertyMatchView:
    spatial: PropertyDistanceMatch
    road_distance_km: float | None
    road_duration_minutes: float | None
    links: tuple[PropertySourceLink, ...] = ()


@dataclass(frozen=True, slots=True)
class JobMatchView:
    fit: JobFitView
    properties: tuple[PropertyMatchView, ...]


def _profile_or_503(db: Session):
    profile = get_seed_profile(db)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Kandidatenprofil ist noch nicht initialisiert.",
        )
    return profile


def _property_links(
    db: Session,
    property_ids: set[int],
) -> dict[int, tuple[PropertySourceLink, ...]]:
    if not property_ids:
        return {}

    rows = db.execute(
        select(PropertyListing.property_id, PropertyListing.url, Source.name)
        .join(Source, Source.id == PropertyListing.source_id)
        .where(
            PropertyListing.property_id.in_(property_ids),
            PropertyListing.status == ListingStatus.ACTIVE,
        )
        .order_by(PropertyListing.property_id, Source.name, PropertyListing.id)
    )

    links: dict[int, list[PropertySourceLink]] = defaultdict(list)
    seen: dict[int, set[str]] = defaultdict(set)
    for property_id, url, source_name in rows:
        if not url or url in seen[property_id]:
            continue
        seen[property_id].add(url)
        links[property_id].append(PropertySourceLink(label=source_name, url=url))
    return {property_id: tuple(items) for property_id, items in links.items()}


def _attach_property_links(
    db: Session,
    groups: list[JobMatchView],
) -> list[JobMatchView]:
    property_ids = {
        item.spatial.property_id
        for group in groups
        for item in group.properties
    }
    links = _property_links(db, property_ids)
    return [
        JobMatchView(
            fit=group.fit,
            properties=tuple(
                PropertyMatchView(
                    spatial=item.spatial,
                    road_distance_km=item.road_distance_km,
                    road_duration_minutes=item.road_duration_minutes,
                    links=links.get(item.spatial.property_id, ()),
                )
                for item in group.properties
            ),
        )
        for group in groups
    ]


def _road_groups(
    db: Session,
    *,
    radius_km: float,
    job_limit: int,
    properties_per_job: int,
) -> list[JobMatchView]:
    settings = get_settings()
    with OSRMClient(
        settings.routing_base_url,
        timeout_seconds=settings.routing_timeout_seconds,
        max_table_coordinates=settings.routing_max_table_coordinates,
    ) as router:
        groups = load_road_candidate_matches(
            db,
            router,
            radius_km=radius_km,
            job_limit=job_limit,
            properties_per_job=properties_per_job,
            prefilter_properties_per_job=max(
                properties_per_job,
                settings.routing_prefilter_properties_per_job,
            ),
        )
    return [
        JobMatchView(
            fit=group.spatial.fit,
            properties=tuple(
                PropertyMatchView(
                    spatial=item.spatial,
                    road_distance_km=item.road_distance_km,
                    road_duration_minutes=item.road_duration_minutes,
                )
                for item in group.properties
            ),
        )
        for group in groups
    ]


def _air_groups(
    db: Session,
    *,
    radius_km: float,
    job_limit: int,
    properties_per_job: int,
) -> list[JobMatchView]:
    groups = load_spatial_candidate_matches(
        db,
        radius_km=radius_km,
        job_limit=job_limit,
        properties_per_job=properties_per_job,
    )
    return [
        JobMatchView(
            fit=group.fit,
            properties=tuple(
                PropertyMatchView(
                    spatial=item,
                    road_distance_km=None,
                    road_duration_minutes=None,
                )
                for item in group.properties
            ),
        )
        for group in groups
    ]


def _eur_label(value: Decimal | None) -> str:
    if value is None:
        return "Preis auf Anfrage"
    return f"{int(value):,} €".replace(",", ".")


def _area_label(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{float(value):g} m²"


@router.get("/matches")
def matches_page(
    request: Request,
    _: AdminDependency,
    db: Annotated[Session, get_db],
    radius_km: Annotated[float, Query(ge=5.0, le=100.0)] = 50.0,
    stellen: Annotated[int, Query(ge=1, le=100)] = 20,
    haeuser: Annotated[int, Query(ge=1, le=10)] = 5,
):
    profile = _profile_or_503(db)
    settings = get_settings()

    routing_mode = "air"
    routing_notice: str | None = None
    if settings.routing_enabled:
        try:
            groups = _road_groups(
                db,
                radius_km=radius_km,
                job_limit=stellen,
                properties_per_job=haeuser,
            )
            routing_mode = "road"
        except RoutingError:
            groups = _air_groups(
                db,
                radius_km=radius_km,
                job_limit=stellen,
                properties_per_job=haeuser,
            )
            routing_notice = (
                "Die Straßenberechnung ist vorübergehend nicht erreichbar. "
                "Entfernungen werden als Luftlinie angezeigt."
            )
    else:
        groups = _air_groups(
            db,
            radius_km=radius_km,
            job_limit=stellen,
            properties_per_job=haeuser,
        )
        routing_notice = (
            "Die Straßenberechnung ist nicht aktiviert. "
            "Entfernungen werden als Luftlinie angezeigt."
        )

    groups = _attach_property_links(db, groups)
    property_count = sum(len(group.properties) for group in groups)

    return templates.TemplateResponse(
        request=request,
        name="admin_matches.html",
        context={
            "profile": profile,
            "groups": groups,
            "radius_km": radius_km,
            "job_limit": stellen,
            "properties_per_job": haeuser,
            "routing_mode": routing_mode,
            "routing_notice": routing_notice,
            "property_count": property_count,
            "annual_salary_label": annual_salary_label,
            "eur_label": _eur_label,
            "area_label": _area_label,
        },
    )
