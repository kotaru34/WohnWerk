from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates
from geoalchemy2 import Geometry
from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.orm import Session

from app.admin import AdminDependency
from app.config import get_settings
from app.database import get_db
from app.geo import radius_metres
from app.jobs.candidate_profile_seed import PROFILE_SLUG
from app.jobs.fit_store import JobFitView, annual_salary_label, load_live_job_fit
from app.matching import PropertyDistanceMatch, SpatialJobMatch
from app.models import JobLocation, ListingStatus, Property, PropertyListing, Source
from app.road_matching import refine_spatial_job_with_road_routes
from app.routing import OSRMClient, RoutingError, RoutingPoint

router = APIRouter(tags=["site"])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

DbDependency = Annotated[Session, Depends(get_db)]
HOUSE_PAGE_SIZE = 36
NEARBY_HOUSE_PAGE_SIZE = 40


@dataclass(frozen=True, slots=True)
class PropertySourceView:
    label: str
    url: str
    display_area_m2: Decimal | None = None
    primary_image_url: str | None = None


@dataclass(frozen=True, slots=True)
class PropertyView:
    property: Property
    sources: tuple[PropertySourceView, ...]

    @property
    def image_url(self) -> str | None:
        return next((item.primary_image_url for item in self.sources if item.primary_image_url), None)

    @property
    def neutral_area_m2(self) -> Decimal | None:
        if self.property.living_area_m2 is not None:
            return None
        values = {
            item.display_area_m2
            for item in self.sources
            if item.display_area_m2 is not None
        }
        if len(values) != 1:
            return None
        return next(iter(values))

    @property
    def visible_plot_area_m2(self) -> Decimal | None:
        plot = self.property.plot_area_m2
        neutral = self.neutral_area_m2
        if plot is None or neutral is None:
            return plot
        tolerance = max(Decimal(1), max(abs(plot), abs(neutral)) * Decimal("0.01"))
        return None if abs(plot - neutral) <= tolerance else plot


@dataclass(frozen=True, slots=True)
class NearbyJobView:
    fit: JobFitView
    distance_km: float
    location_label: str
    road_distance_km: float | None = None
    road_duration_minutes: float | None = None


@dataclass(frozen=True, slots=True)
class NearbyHouseView:
    spatial: PropertyDistanceMatch
    property: PropertyView
    road_distance_km: float | None = None
    road_duration_minutes: float | None = None


def _payload_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _payload_image(payload: dict) -> str | None:
    for key in ("primary_image_url", "image_url", "thumbnail_url"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            return value
    return None


def _property_sources(
    db: Session,
    property_ids: set[int],
) -> dict[int, tuple[PropertySourceView, ...]]:
    if not property_ids:
        return {}
    rows = db.execute(
        select(
            PropertyListing.property_id,
            PropertyListing.url,
            PropertyListing.raw_payload,
            Source.name,
        )
        .join(Source, Source.id == PropertyListing.source_id)
        .where(
            PropertyListing.property_id.in_(property_ids),
            PropertyListing.status == ListingStatus.ACTIVE,
        )
        .order_by(PropertyListing.property_id, Source.name, PropertyListing.id)
    )
    output: dict[int, list[PropertySourceView]] = {}
    seen_urls: dict[int, set[str]] = {}
    for property_id, url, raw_payload, source_name in rows:
        property_id = int(property_id)
        if not url or url in seen_urls.setdefault(property_id, set()):
            continue
        seen_urls[property_id].add(url)
        payload = raw_payload or {}
        output.setdefault(property_id, []).append(
            PropertySourceView(
                label=source_name,
                url=url,
                display_area_m2=(
                    _payload_decimal(payload.get("display_area_m2"))
                    if source_name == "immmo.at"
                    else None
                ),
                primary_image_url=_payload_image(payload),
            )
        )
    return {key: tuple(value) for key, value in output.items()}


def _property_views(db: Session, rows: list[Property]) -> list[PropertyView]:
    sources = _property_sources(db, {row.id for row in rows})
    return [PropertyView(property=row, sources=sources.get(row.id, ())) for row in rows]


def _eur_label(value: Decimal | None) -> str:
    if value is None:
        return "Preis auf Anfrage"
    return f"€ {value:,.0f}".replace(",", ".")


def _area_label(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:,.0f} m²".replace(",", ".")


def _visible_fit_rows(db: Session) -> list[JobFitView]:
    """Return every current relevant job except explicit candidate-hidden rows."""
    return [
        row
        for row in load_live_job_fit(db, profile_slug=PROFILE_SLUG)
        if not row.hidden
    ]


def _properties_within_radius_for_job_stmt(job_id: int, radius_km: float):
    if job_id <= 0:
        raise ValueError("job_id must be greater than zero")
    distance_m = func.ST_Distance(Property.location, JobLocation.location)
    candidates = (
        select(
            Property.id.label("property_id"),
            Property.title.label("title"),
            Property.postal_code.label("postal_code"),
            Property.city.label("city"),
            Property.price_eur.label("price_eur"),
            Property.living_area_m2.label("living_area_m2"),
            Property.plot_area_m2.label("plot_area_m2"),
            JobLocation.id.label("job_location_id"),
            JobLocation.postal_code.label("job_postal_code"),
            JobLocation.city.label("job_city"),
            JobLocation.location_text.label("job_location_text"),
            (distance_m / 1000.0).label("distance_km"),
            func.row_number()
            .over(
                partition_by=Property.id,
                order_by=(distance_m.asc(), JobLocation.id.asc()),
            )
            .label("nearest_location_rank"),
        )
        .select_from(Property)
        .join(
            JobLocation,
            and_(
                JobLocation.job_id == job_id,
                JobLocation.location.is_not(None),
                func.ST_DWithin(
                    Property.location,
                    JobLocation.location,
                    radius_metres(radius_km),
                ),
            ),
        )
        .where(
            Property.status == ListingStatus.ACTIVE,
            Property.location.is_not(None),
        )
        .subquery("catalog_property_job_candidates")
    )
    return select(
        candidates.c.property_id,
        candidates.c.title,
        candidates.c.postal_code,
        candidates.c.city,
        candidates.c.price_eur,
        candidates.c.living_area_m2,
        candidates.c.plot_area_m2,
        candidates.c.job_location_id,
        candidates.c.job_postal_code,
        candidates.c.job_city,
        candidates.c.job_location_text,
        candidates.c.distance_km,
    ).where(candidates.c.nearest_location_rank == 1)


def _nearby_jobs(db: Session, property_id: int, radius_km: float) -> list[NearbyJobView]:
    fit_rows = _visible_fit_rows(db)
    fit_by_id = {row.job.id: row for row in fit_rows}
    if not fit_by_id:
        return []

    distance_m = func.ST_Distance(Property.location, JobLocation.location)
    candidates = (
        select(
            JobLocation.job_id.label("job_id"),
            JobLocation.postal_code.label("postal_code"),
            JobLocation.city.label("city"),
            JobLocation.location_text.label("location_text"),
            (distance_m / 1000.0).label("distance_km"),
            func.row_number()
            .over(
                partition_by=JobLocation.job_id,
                order_by=(distance_m.asc(), JobLocation.id.asc()),
            )
            .label("nearest_location_rank"),
        )
        .select_from(Property)
        .join(
            JobLocation,
            and_(
                JobLocation.job_id.in_(fit_by_id),
                JobLocation.location.is_not(None),
                func.ST_DWithin(
                    Property.location,
                    JobLocation.location,
                    radius_metres(radius_km),
                ),
            ),
        )
        .where(Property.id == property_id, Property.location.is_not(None))
        .subquery("jobs_near_property")
    )
    rows = list(
        db.execute(
            select(candidates)
            .where(candidates.c.nearest_location_rank == 1)
            .order_by(candidates.c.distance_km.asc(), candidates.c.job_id.asc())
        ).mappings()
    )
    output = [
        NearbyJobView(
            fit=fit_by_id[int(row["job_id"])],
            distance_km=float(row["distance_km"]),
            location_label=(
                " ".join(value for value in (row["postal_code"], row["city"]) if value)
                or row["location_text"]
                or "Ort unbekannt"
            ),
        )
        for row in rows
    ]
    return _route_jobs_from_property(db, property_id, output)


def _route_jobs_from_property(
    db: Session,
    property_id: int,
    jobs: list[NearbyJobView],
) -> list[NearbyJobView]:
    settings = get_settings()
    if not settings.routing_enabled or not jobs:
        return jobs

    property_geometry = cast(Property.location, Geometry(geometry_type="POINT", srid=4326))
    origin = db.execute(
        select(
            func.ST_X(property_geometry).label("longitude"),
            func.ST_Y(property_geometry).label("latitude"),
        ).where(Property.id == property_id, Property.location.is_not(None))
    ).one_or_none()
    if origin is None:
        return jobs

    job_ids = {item.fit.job.id for item in jobs}
    geometry = cast(JobLocation.location, Geometry(geometry_type="POINT", srid=4326))
    location_rows = list(
        db.execute(
            select(
                JobLocation.job_id,
                func.ST_X(geometry).label("longitude"),
                func.ST_Y(geometry).label("latitude"),
            )
            .where(JobLocation.job_id.in_(job_ids), JobLocation.location.is_not(None))
            .order_by(JobLocation.job_id, JobLocation.id)
        )
    )
    locations_by_job: dict[int, list[RoutingPoint]] = {}
    unique_points: list[RoutingPoint] = []
    point_index: set[RoutingPoint] = set()
    for row in location_rows:
        point = RoutingPoint(longitude=float(row.longitude), latitude=float(row.latitude))
        locations_by_job.setdefault(int(row.job_id), []).append(point)
        if point not in point_index:
            point_index.add(point)
            unique_points.append(point)

    if not unique_points:
        return jobs

    try:
        with OSRMClient(
            settings.routing_base_url,
            timeout_seconds=settings.routing_timeout_seconds,
            max_table_coordinates=settings.routing_max_table_coordinates,
        ) as client:
            estimates = client.table(
                RoutingPoint(longitude=float(origin.longitude), latitude=float(origin.latitude)),
                unique_points,
            )
    except RoutingError:
        return jobs

    by_point = dict(zip(unique_points, estimates, strict=True))
    refined: list[NearbyJobView] = []
    for item in jobs:
        reachable = [
            by_point[point]
            for point in locations_by_job.get(item.fit.job.id, [])
            if point in by_point and by_point[point].reachable
        ]
        if not reachable:
            refined.append(item)
            continue
        estimate = min(
            reachable,
            key=lambda value: (
                value.duration_minutes if value.duration_minutes is not None else math.inf,
                value.distance_km if value.distance_km is not None else math.inf,
            ),
        )
        refined.append(
            NearbyJobView(
                fit=item.fit,
                distance_km=item.distance_km,
                location_label=item.location_label,
                road_distance_km=estimate.distance_km,
                road_duration_minutes=estimate.duration_minutes,
            )
        )
    refined.sort(
        key=lambda item: (
            item.road_duration_minutes if item.road_duration_minutes is not None else math.inf,
            item.distance_km,
            -(item.fit.result.score or 0),
            item.fit.job.id,
        )
    )
    return refined


@router.get("/houses", include_in_schema=False)
def houses_page(
    request: Request,
    _: AdminDependency,
    db: DbDependency,
    ort: Annotated[str, Query()] = "",
    preis_von: Annotated[Decimal | None, Query(ge=0)] = None,
    preis_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    wohn_von: Annotated[Decimal | None, Query(ge=0)] = None,
    wohn_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    grund_von: Annotated[Decimal | None, Query(ge=0)] = None,
    grund_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    seite: Annotated[int, Query(ge=1)] = 1,
):
    conditions = [Property.status == ListingStatus.ACTIVE]
    normalized_location = ort.strip()
    if normalized_location:
        like = f"%{normalized_location}%"
        conditions.append(
            or_(
                Property.postal_code.ilike(like),
                Property.city.ilike(like),
            )
        )
    if preis_von is not None:
        conditions.append(Property.price_eur >= preis_von)
    if preis_bis is not None:
        conditions.append(Property.price_eur <= preis_bis)
    if wohn_von is not None:
        conditions.append(Property.living_area_m2 >= wohn_von)
    if wohn_bis is not None:
        conditions.append(Property.living_area_m2 <= wohn_bis)
    if grund_von is not None:
        conditions.append(Property.plot_area_m2 >= grund_von)
    if grund_bis is not None:
        conditions.append(Property.plot_area_m2 <= grund_bis)

    total = int(db.scalar(select(func.count()).select_from(Property).where(*conditions)) or 0)
    page_count = max(1, math.ceil(total / HOUSE_PAGE_SIZE))
    if seite > page_count and total:
        raise HTTPException(status_code=404, detail="Seite nicht gefunden.")

    rows = list(
        db.scalars(
            select(Property)
            .where(*conditions)
            .order_by(Property.last_seen_at.desc(), Property.id.desc())
            .offset((seite - 1) * HOUSE_PAGE_SIZE)
            .limit(HOUSE_PAGE_SIZE)
        )
    )
    return templates.TemplateResponse(
        request=request,
        name="houses.html",
        context={
            "rows": _property_views(db, rows),
            "total": total,
            "page": seite,
            "page_count": page_count,
            "filters": {
                "ort": ort,
                "preis_von": preis_von,
                "preis_bis": preis_bis,
                "wohn_von": wohn_von,
                "wohn_bis": wohn_bis,
                "grund_von": grund_von,
                "grund_bis": grund_bis,
            },
            "eur_label": _eur_label,
            "area_label": _area_label,
        },
    )


@router.get("/houses/{property_id}", include_in_schema=False)
def house_detail(
    property_id: int,
    request: Request,
    _: AdminDependency,
    db: DbDependency,
    radius_km: Annotated[float, Query(ge=5, le=100)] = 50.0,
):
    property_row = db.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.status == ListingStatus.ACTIVE,
        )
    )
    if property_row is None:
        raise HTTPException(status_code=404, detail="Immobilie nicht gefunden.")
    view = _property_views(db, [property_row])[0]
    jobs = _nearby_jobs(db, property_id, radius_km)
    return templates.TemplateResponse(
        request=request,
        name="house_detail.html",
        context={
            "house": view,
            "jobs": jobs,
            "radius_km": radius_km,
            "eur_label": _eur_label,
            "area_label": _area_label,
            "annual_salary_label": annual_salary_label,
        },
    )


@router.get("/jobs/{job_id}", include_in_schema=False)
def job_detail(
    job_id: int,
    request: Request,
    _: AdminDependency,
    db: DbDependency,
    radius_km: Annotated[float, Query(ge=5, le=100)] = 50.0,
    seite: Annotated[int, Query(ge=1)] = 1,
):
    fit = next((row for row in _visible_fit_rows(db) if row.job.id == job_id), None)
    if fit is None:
        raise HTTPException(status_code=404, detail="Stelle nicht gefunden.")

    base = _properties_within_radius_for_job_stmt(job_id, radius_km)
    total = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    page_count = max(1, math.ceil(total / NEARBY_HOUSE_PAGE_SIZE))
    if seite > page_count and total:
        raise HTTPException(status_code=404, detail="Seite nicht gefunden.")

    rows = list(
        db.execute(
            base.order_by(
                base.selected_columns.distance_km.asc(),
                base.selected_columns.property_id.asc(),
            )
            .offset((seite - 1) * NEARBY_HOUSE_PAGE_SIZE)
            .limit(NEARBY_HOUSE_PAGE_SIZE)
        ).mappings()
    )
    spatial = [
        PropertyDistanceMatch(
            property_id=int(row["property_id"]),
            title=row["title"],
            postal_code=row["postal_code"],
            city=row["city"],
            price_eur=row["price_eur"],
            living_area_m2=row["living_area_m2"],
            plot_area_m2=row["plot_area_m2"],
            job_location_id=int(row["job_location_id"]),
            job_postal_code=row["job_postal_code"],
            job_city=row["job_city"],
            job_location_text=row["job_location_text"],
            distance_km=float(row["distance_km"]),
        )
        for row in rows
    ]
    road_by_property = {}
    settings = get_settings()
    if settings.routing_enabled and spatial:
        try:
            with OSRMClient(
                settings.routing_base_url,
                timeout_seconds=settings.routing_timeout_seconds,
                max_table_coordinates=settings.routing_max_table_coordinates,
            ) as client:
                refined = refine_spatial_job_with_road_routes(
                    db,
                    client,
                    SpatialJobMatch(fit=fit, properties=tuple(spatial)),
                )
            road_by_property = {item.spatial.property_id: item for item in refined}
        except RoutingError:
            road_by_property = {}

    property_ids = {item.property_id for item in spatial}
    properties = list(db.scalars(select(Property).where(Property.id.in_(property_ids))))
    property_views = {item.property.id: item for item in _property_views(db, properties)}
    houses = [
        NearbyHouseView(
            spatial=item,
            property=property_views[item.property_id],
            road_distance_km=(
                road_by_property[item.property_id].road_distance_km
                if item.property_id in road_by_property
                else None
            ),
            road_duration_minutes=(
                road_by_property[item.property_id].road_duration_minutes
                if item.property_id in road_by_property
                else None
            ),
        )
        for item in spatial
        if item.property_id in property_views
    ]

    return templates.TemplateResponse(
        request=request,
        name="job_detail.html",
        context={
            "fit": fit,
            "houses": houses,
            "radius_km": radius_km,
            "total": total,
            "page": seite,
            "page_count": page_count,
            "eur_label": _eur_label,
            "area_label": _area_label,
            "annual_salary_label": annual_salary_label,
        },
    )
