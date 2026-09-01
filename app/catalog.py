from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from geoalchemy2 import Geometry
from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.orm import Session

from app.admin import AdminDependency, CsrfDependency, _csrf_token
from app.candidate_activity import (
    CandidatePropertyState,
    is_new_unviewed,
    load_property_states,
    mark_job_viewed,
    mark_property_viewed,
    novelty_baseline,
    property_curation_condition,
    set_property_favorite,
    set_property_hidden,
)
from app.config import get_settings
from app.database import get_db
from app.geo import radius_metres
from app.house_filters import (
    HouseFilters,
    house_filter_summary,
    load_house_filters,
    resolve_house_filters,
    save_house_filters,
)
from app.jobs.candidate_profile_seed import PROFILE_SLUG
from app.jobs.candidate_profile_store import get_seed_profile
from app.jobs.fit_store import JobFitView, annual_salary_label, load_live_job_fit
from app.matching import PropertyDistanceMatch, SpatialJobMatch
from app.models import JobLocation, ListingStatus, Property, PropertyListing, Source
from app.property_acquisition import PROPERTY_MAX_PRICE_EUR, PROPERTY_MIN_PRICE_EUR
from app.property_areas import usable_area_property_condition
from app.property_images import cached_image_urls, local_image_path
from app.property_location_filter import PropertyRadiusFilter, resolve_property_radius_filter
from app.property_visibility import product_visible_property_condition
from app.road_matching import refine_spatial_job_with_road_routes
from app.routing import OSRMClient, RoutingError, RoutingPoint

router = APIRouter(tags=["site"])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

DbDependency = Annotated[Session, Depends(get_db)]
HOUSE_PAGE_SIZE = 36
NEARBY_HOUSE_PAGE_SIZE = 40
HOUSE_VIEWS = {
    "alle": "Alle",
    "favoriten": "Favoriten",
    "ausgeblendet": "Ausgeblendet",
}


@dataclass(frozen=True, slots=True)
class PropertySourceView:
    label: str
    url: str
    display_area_m2: Decimal | None = None
    usable_area_m2: Decimal | None = None


@dataclass(frozen=True, slots=True)
class PropertyView:
    property: Property
    sources: tuple[PropertySourceView, ...]

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
    def visible_usable_area_m2(self) -> Decimal | None:
        values = {
            item.usable_area_m2
            for item in self.sources
            if item.usable_area_m2 is not None
        }
        if len(values) != 1:
            return None
        usable = next(iter(values))
        living = self.property.living_area_m2
        if living is None:
            return usable
        tolerance = max(Decimal(1), max(abs(living), abs(usable)) * Decimal("0.01"))
        return None if abs(living - usable) <= tolerance else usable

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


def _profile_or_503(db: Session):
    profile = get_seed_profile(db)
    if profile is None:
        raise HTTPException(status_code=503, detail="Kandidatenprofil ist noch nicht initialisiert.")
    return profile


def _payload_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
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
                usable_area_m2=(
                    _payload_decimal(payload.get("detail_usable_area_m2"))
                    or _payload_decimal(payload.get("explicit_usable_area_m2"))
                ),
            )
        )
    return {key: tuple(value) for key, value in output.items()}


def _property_views(db: Session, rows: list[Property]) -> list[PropertyView]:
    sources = _property_sources(db, {row.id for row in rows})
    return [PropertyView(property=row, sources=sources.get(row.id, ())) for row in rows]


def _property_ui_state(db: Session, profile, rows: list[Property]):
    property_ids = {row.id for row in rows}
    states = load_property_states(db, profile.id, property_ids)
    baseline = novelty_baseline(db, profile)
    new_ids = {
        row.id
        for row in rows
        if is_new_unviewed(
            first_seen_at=row.first_seen_at,
            baseline=baseline,
            viewed_at=states.get(row.id, CandidatePropertyState()).viewed_at,
        )
    }
    return states, new_ids, cached_image_urls(db, property_ids)


def _eur_label(value: Decimal | None) -> str:
    if value is None:
        return "Preis auf Anfrage"
    return f"€ {value:,.0f}".replace(",", ".")


def _area_label(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:,.0f} m²".replace(",", ".")


def _visible_fit_rows(db: Session) -> list[JobFitView]:
    return [
        row
        for row in load_live_job_fit(db, profile_slug=PROFILE_SLUG)
        if not row.hidden
    ]


def _property_filter_conditions(
    filters: HouseFilters,
    *,
    radius_filter: PropertyRadiusFilter | None = None,
) -> list:
    conditions = []
    normalized_location = filters.ort.strip()
    if normalized_location:
        if filters.radius_km is not None:
            if radius_filter is None:
                raise ValueError("resolved radius filter is required for a radius query")
            conditions.append(radius_filter.condition)
        else:
            like = f"%{normalized_location}%"
            conditions.append(
                or_(
                    Property.postal_code.ilike(like),
                    Property.city.ilike(like),
                )
            )
    if filters.preis_von is not None:
        conditions.append(Property.price_eur >= filters.preis_von)
    if filters.preis_bis is not None:
        conditions.append(Property.price_eur <= filters.preis_bis)
    if filters.wohn_von is not None:
        conditions.append(Property.living_area_m2 >= filters.wohn_von)
    if filters.wohn_bis is not None:
        conditions.append(Property.living_area_m2 <= filters.wohn_bis)
    usable_condition = usable_area_property_condition(filters.nutz_von, filters.nutz_bis)
    if usable_condition is not None:
        conditions.append(usable_condition)
    if filters.grund_von is not None:
        conditions.append(Property.plot_area_m2 >= filters.grund_von)
    if filters.grund_bis is not None:
        conditions.append(Property.plot_area_m2 <= filters.grund_bis)
    return conditions


def _product_property_conditions() -> list:
    return [
        Property.status == ListingStatus.ACTIVE,
        product_visible_property_condition(),
    ]


def _properties_within_radius_for_job_stmt(
    job_id: int,
    radius_km: float,
    house_filters: HouseFilters | None = None,
    profile_id: int | None = None,
    *,
    db: Session | None = None,
):
    if job_id <= 0:
        raise ValueError("job_id must be greater than zero")
    filters = house_filters or HouseFilters()
    radius_filter = None
    if filters.ort and filters.radius_km is not None:
        if db is None:
            raise ValueError("db session is required for a saved house radius filter")
        radius_filter = resolve_property_radius_filter(db, filters)
    curation = [property_curation_condition(profile_id, "alle")] if profile_id else []
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
            *_product_property_conditions(),
            *curation,
            Property.location.is_not(None),
            *_property_filter_conditions(filters, radius_filter=radius_filter),
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
        .where(
            Property.id == property_id,
            Property.location.is_not(None),
            product_visible_property_condition(),
        )
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


def _safe_return_to(value: str) -> str:
    return value if value.startswith(("/houses", "/jobs")) else "/houses"


@router.get("/media/properties/{property_id}", include_in_schema=False)
def property_image(
    property_id: int,
    _: AdminDependency,
    db: DbDependency,
):
    path = local_image_path(db, property_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Vorschaubild nicht gefunden.")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/houses", include_in_schema=False)
def houses_page(
    request: Request,
    _: AdminDependency,
    db: DbDependency,
    ort: Annotated[str, Query()] = "",
    radius_km: Annotated[Decimal | None, Query(ge=1, le=250)] = None,
    preis_von: Annotated[Decimal | None, Query(ge=0)] = None,
    preis_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    wohn_von: Annotated[Decimal | None, Query(ge=0)] = None,
    wohn_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    nutz_von: Annotated[Decimal | None, Query(ge=0)] = None,
    nutz_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    grund_von: Annotated[Decimal | None, Query(ge=0)] = None,
    grund_bis: Annotated[Decimal | None, Query(ge=0)] = None,
    ansicht: Annotated[str, Query()] = "alle",
    seite: Annotated[int, Query(ge=1)] = 1,
):
    profile = _profile_or_503(db)
    if ansicht not in HOUSE_VIEWS:
        raise HTTPException(status_code=400, detail="Ungültige Häuseransicht.")
    filters = resolve_house_filters(
        request,
        ort=ort,
        radius_km=radius_km,
        preis_von=preis_von,
        preis_bis=preis_bis,
        wohn_von=wohn_von,
        wohn_bis=wohn_bis,
        nutz_von=nutz_von,
        nutz_bis=nutz_bis,
        grund_von=grund_von,
        grund_bis=grund_bis,
    )
    radius_filter = resolve_property_radius_filter(db, filters)
    conditions = [
        *_product_property_conditions(),
        property_curation_condition(profile.id, ansicht),
        *_property_filter_conditions(filters, radius_filter=radius_filter),
    ]

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
    states, new_ids, image_urls = _property_ui_state(db, profile, rows)
    stats = {
        "favoriten": int(
            db.scalar(
                select(func.count())
                .select_from(Property)
                .where(
                    *_product_property_conditions(),
                    property_curation_condition(profile.id, "favoriten"),
                )
            )
            or 0
        ),
        "ausgeblendet": int(
            db.scalar(
                select(func.count())
                .select_from(Property)
                .where(
                    *_product_property_conditions(),
                    property_curation_condition(profile.id, "ausgeblendet"),
                )
            )
            or 0
        ),
    }
    response = templates.TemplateResponse(
        request=request,
        name="houses.html",
        context={
            "rows": _property_views(db, rows),
            "states": states,
            "new_ids": new_ids,
            "image_urls": image_urls,
            "total": total,
            "page": seite,
            "page_count": page_count,
            "filters": filters,
            "location_filter_error": radius_filter.error if radius_filter is not None else None,
            "house_views": HOUSE_VIEWS,
            "selected_view": ansicht,
            "stats": stats,
            "system_price_min": PROPERTY_MIN_PRICE_EUR,
            "system_price_max": PROPERTY_MAX_PRICE_EUR,
            "eur_label": _eur_label,
            "area_label": _area_label,
            "csrf_token": _csrf_token(),
        },
    )
    save_house_filters(response, filters)
    return response


@router.post("/houses/{property_id}/favorite", include_in_schema=False)
def update_property_favorite(
    property_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    favorite: Annotated[str, Form()],
    return_to: Annotated[str, Form()] = "/houses",
):
    profile = _profile_or_503(db)
    try:
        set_property_favorite(db, profile, property_id, favorite=favorite == "1")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Immobilie nicht gefunden.") from exc
    return RedirectResponse(_safe_return_to(return_to), status_code=303)


@router.post("/houses/{property_id}/hidden", include_in_schema=False)
def update_property_hidden(
    property_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    hidden: Annotated[str, Form()],
    return_to: Annotated[str, Form()] = "/houses",
):
    profile = _profile_or_503(db)
    try:
        set_property_hidden(db, profile, property_id, hidden=hidden == "1")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Immobilie nicht gefunden.") from exc
    return RedirectResponse(_safe_return_to(return_to), status_code=303)


@router.get("/houses/{property_id}", include_in_schema=False)
def house_detail(
    property_id: int,
    request: Request,
    _: AdminDependency,
    db: DbDependency,
    radius_km: Annotated[float, Query(ge=5, le=100)] = 50.0,
):
    profile = _profile_or_503(db)
    property_row = db.scalar(
        select(Property).where(
            Property.id == property_id,
            *_product_property_conditions(),
            property_curation_condition(profile.id, "alle"),
        )
    )
    if property_row is None:
        raise HTTPException(status_code=404, detail="Immobilie nicht gefunden.")
    mark_property_viewed(db, profile, property_id)
    states, _new_ids, image_urls = _property_ui_state(db, profile, [property_row])
    view = _property_views(db, [property_row])[0]
    jobs = _nearby_jobs(db, property_id, radius_km)
    return templates.TemplateResponse(
        request=request,
        name="house_detail.html",
        context={
            "house": view,
            "house_state": states.get(property_id, CandidatePropertyState()),
            "image_url": image_urls.get(property_id),
            "jobs": jobs,
            "radius_km": radius_km,
            "eur_label": _eur_label,
            "area_label": _area_label,
            "annual_salary_label": annual_salary_label,
            "csrf_token": _csrf_token(),
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
    profile = _profile_or_503(db)
    fit = next((row for row in _visible_fit_rows(db) if row.job.id == job_id), None)
    if fit is None:
        raise HTTPException(status_code=404, detail="Stelle nicht gefunden.")
    mark_job_viewed(db, profile, job_id)
    fit = next((row for row in _visible_fit_rows(db) if row.job.id == job_id), fit)

    filters = load_house_filters(request)
    base = _properties_within_radius_for_job_stmt(
        job_id,
        radius_km,
        filters,
        profile_id=profile.id,
        db=db,
    )
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
    states, new_ids, image_urls = _property_ui_state(db, profile, properties)
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

    response = templates.TemplateResponse(
        request=request,
        name="job_detail.html",
        context={
            "fit": fit,
            "houses": houses,
            "states": states,
            "new_ids": new_ids,
            "image_urls": image_urls,
            "radius_km": radius_km,
            "total": total,
            "page": seite,
            "page_count": page_count,
            "house_filters": filters,
            "house_filter_summary": house_filter_summary(filters),
            "system_price_min": PROPERTY_MIN_PRICE_EUR,
            "system_price_max": PROPERTY_MAX_PRICE_EUR,
            "eur_label": _eur_label,
            "area_label": _area_label,
            "annual_salary_label": annual_salary_label,
            "csrf_token": _csrf_token(),
        },
    )
    save_house_filters(response, filters)
    return response
