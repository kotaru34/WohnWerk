from __future__ import annotations

from dataclasses import dataclass
from math import inf

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.matching import PropertyDistanceMatch, SpatialJobMatch, load_spatial_candidate_matches
from app.models import JobLocation, Property
from app.routing import OSRMClient, RouteEstimate, RoutingPoint


@dataclass(frozen=True, slots=True)
class RoadPropertyMatch:
    spatial: PropertyDistanceMatch
    road_distance_km: float | None
    road_duration_minutes: float | None
    road_job_location_id: int | None
    road_job_location_label: str | None

    @property
    def reachable(self) -> bool:
        return self.road_distance_km is not None and self.road_duration_minutes is not None


@dataclass(frozen=True, slots=True)
class RoadSpatialJobMatch:
    spatial: SpatialJobMatch
    properties: tuple[RoadPropertyMatch, ...]


@dataclass(frozen=True, slots=True)
class _JobRoutingLocation:
    id: int
    point: RoutingPoint
    label: str


def load_road_candidate_matches(
    session: Session,
    router: OSRMClient,
    *,
    radius_km: float = 50.0,
    job_limit: int = 10,
    properties_per_job: int = 5,
    prefilter_properties_per_job: int = 75,
) -> list[RoadSpatialJobMatch]:
    """Refine cheap PostGIS candidates with fastest-route driving metrics.

    `radius_km` is both the safe geodesic prefilter and the maximum accepted road
    distance. A route that is at most N kilometres cannot have endpoints more than N
    kilometres apart geodesically, so the PostGIS radius cannot exclude a valid route.

    Only the closest `prefilter_properties_per_job` straight-line candidates are sent
    to the router. This keeps routing bounded instead of creating an all-properties
    matrix. Every physical location of a multi-site job is evaluated and the fastest
    reachable route is retained for each property.
    """
    if prefilter_properties_per_job < properties_per_job:
        raise ValueError("prefilter_properties_per_job must be >= properties_per_job")

    spatial_groups = load_spatial_candidate_matches(
        session,
        radius_km=radius_km,
        job_limit=job_limit,
        properties_per_job=prefilter_properties_per_job,
    )

    output: list[RoadSpatialJobMatch] = []
    for group in spatial_groups:
        refined = refine_spatial_job_with_road_routes(session, router, group)
        eligible = [
            item
            for item in refined
            if item.road_distance_km is not None and item.road_distance_km <= radius_km
        ]
        eligible.sort(key=_road_rank_key)
        output.append(
            RoadSpatialJobMatch(
                spatial=group,
                properties=tuple(eligible[:properties_per_job]),
            )
        )
    return output


def refine_spatial_job_with_road_routes(
    session: Session,
    router: OSRMClient,
    group: SpatialJobMatch,
) -> list[RoadPropertyMatch]:
    if not group.properties:
        return []

    property_points = _property_points(
        session,
        {item.property_id for item in group.properties},
    )
    job_locations = _job_routing_locations(session, group.fit.job.id)
    if not property_points or not job_locations:
        return [_unreachable(item) for item in group.properties]

    unique_destinations: list[RoutingPoint] = []
    destination_index: dict[RoutingPoint, int] = {}
    property_destination: dict[int, RoutingPoint] = {}
    for item in group.properties:
        point = property_points.get(item.property_id)
        if point is None:
            continue
        property_destination[item.property_id] = point
        if point not in destination_index:
            destination_index[point] = len(unique_destinations)
            unique_destinations.append(point)

    best_by_property: dict[int, tuple[RouteEstimate, _JobRoutingLocation]] = {}
    for job_location in job_locations:
        route_estimates = router.table(job_location.point, unique_destinations)
        by_point = dict(zip(unique_destinations, route_estimates, strict=True))
        for item in group.properties:
            point = property_destination.get(item.property_id)
            if point is None:
                continue
            estimate = by_point[point]
            if not estimate.reachable:
                continue
            current = best_by_property.get(item.property_id)
            if current is None or _estimate_key(estimate, job_location.id) < _estimate_key(
                current[0],
                current[1].id,
            ):
                best_by_property[item.property_id] = (estimate, job_location)

    output: list[RoadPropertyMatch] = []
    for item in group.properties:
        best = best_by_property.get(item.property_id)
        if best is None:
            output.append(_unreachable(item))
            continue
        estimate, job_location = best
        output.append(
            RoadPropertyMatch(
                spatial=item,
                road_distance_km=estimate.distance_km,
                road_duration_minutes=estimate.duration_minutes,
                road_job_location_id=job_location.id,
                road_job_location_label=job_location.label,
            )
        )
    return output


def _unreachable(item: PropertyDistanceMatch) -> RoadPropertyMatch:
    return RoadPropertyMatch(
        spatial=item,
        road_distance_km=None,
        road_duration_minutes=None,
        road_job_location_id=None,
        road_job_location_label=None,
    )


def _estimate_key(estimate: RouteEstimate, job_location_id: int) -> tuple[float, float, int]:
    return (
        estimate.duration_minutes if estimate.duration_minutes is not None else inf,
        estimate.distance_km if estimate.distance_km is not None else inf,
        job_location_id,
    )


def _road_rank_key(item: RoadPropertyMatch) -> tuple[float, float, float, int]:
    return (
        item.road_duration_minutes if item.road_duration_minutes is not None else inf,
        item.road_distance_km if item.road_distance_km is not None else inf,
        item.spatial.distance_km,
        item.spatial.property_id,
    )


def _property_points(session: Session, property_ids: set[int]) -> dict[int, RoutingPoint]:
    if not property_ids:
        return {}
    geometry = cast(Property.location, Geometry(geometry_type="POINT", srid=4326))
    rows = session.execute(
        select(
            Property.id,
            func.ST_X(geometry).label("longitude"),
            func.ST_Y(geometry).label("latitude"),
        ).where(Property.id.in_(property_ids), Property.location.is_not(None))
    )
    return {
        int(row.id): RoutingPoint(longitude=float(row.longitude), latitude=float(row.latitude))
        for row in rows
    }


def _job_routing_locations(session: Session, job_id: int) -> list[_JobRoutingLocation]:
    geometry = cast(JobLocation.location, Geometry(geometry_type="POINT", srid=4326))
    rows = session.execute(
        select(
            JobLocation.id,
            JobLocation.postal_code,
            JobLocation.city,
            JobLocation.location_text,
            func.ST_X(geometry).label("longitude"),
            func.ST_Y(geometry).label("latitude"),
        )
        .where(JobLocation.job_id == job_id, JobLocation.location.is_not(None))
        .order_by(JobLocation.id)
    )
    return [
        _JobRoutingLocation(
            id=int(row.id),
            point=RoutingPoint(longitude=float(row.longitude), latitude=float(row.latitude)),
            label=_job_location_label(row.postal_code, row.city, row.location_text),
        )
        for row in rows
    ]


def _job_location_label(
    postal_code: str | None,
    city: str | None,
    location_text: str | None,
) -> str:
    parts = [value for value in (postal_code, city) if value]
    return " ".join(parts) or (location_text or "Ort unbekannt")
