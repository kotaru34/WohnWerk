from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.geo import radius_metres
from app.jobs.candidate_profile_seed import PROFILE_SLUG
from app.jobs.fit_store import JobFitView, load_live_job_fit, relevant_active_jobs
from app.models import JobLocation, ListingStatus, Property


@dataclass(frozen=True, slots=True)
class GeoCoverage:
    active_properties: int
    located_properties: int
    relevant_jobs: int
    relevant_job_locations: int
    located_job_locations: int
    jobs_with_located_location: int

    @property
    def property_location_ratio(self) -> float:
        return self.located_properties / self.active_properties if self.active_properties else 0.0

    @property
    def job_location_ratio(self) -> float:
        return self.jobs_with_located_location / self.relevant_jobs if self.relevant_jobs else 0.0


@dataclass(frozen=True, slots=True)
class PropertyDistanceMatch:
    property_id: int
    title: str
    postal_code: str | None
    city: str | None
    price_eur: Decimal | None
    living_area_m2: Decimal | None
    plot_area_m2: Decimal | None
    job_location_id: int
    job_postal_code: str | None
    job_city: str | None
    job_location_text: str | None
    distance_km: float

    @property
    def job_location_label(self) -> str:
        parts = [value for value in (self.job_postal_code, self.job_city) if value]
        return " ".join(parts) or (self.job_location_text or "Ort unbekannt")

    @property
    def property_location_label(self) -> str:
        parts = [value for value in (self.postal_code, self.city) if value]
        return " ".join(parts) or "Ort unbekannt"


@dataclass(frozen=True, slots=True)
class SpatialJobMatch:
    fit: JobFitView
    properties: tuple[PropertyDistanceMatch, ...]


def nearest_properties_for_job_stmt(
    job_id: int,
    radius_km: float,
    *,
    limit: int = 25,
):
    """Build an indexed PostGIS query for the nearest active properties to one job.

    A canonical job may have several physical locations. `ST_DWithin` first constrains
    candidate pairs using geography spatial indexes. A window then keeps only the closest
    job location for each property, so one house cannot appear repeatedly for a multi-site
    vacancy. The returned distance is geodesic straight-line distance in kilometres.
    """

    if job_id <= 0:
        raise ValueError("job_id must be greater than zero")
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    distance_m = func.ST_Distance(Property.location, JobLocation.location)
    distance_km = (distance_m / 1000.0).label("distance_km")

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
            distance_km,
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
        .subquery("property_job_location_candidates")
    )

    return (
        select(
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
        )
        .where(candidates.c.nearest_location_rank == 1)
        .order_by(candidates.c.distance_km.asc(), candidates.c.property_id.asc())
        .limit(limit)
    )


def nearest_properties_for_job(
    session: Session,
    job_id: int,
    radius_km: float,
    *,
    limit: int = 25,
) -> list[PropertyDistanceMatch]:
    rows = session.execute(
        nearest_properties_for_job_stmt(job_id, radius_km, limit=limit)
    ).mappings()
    return [
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


def geo_coverage(session: Session) -> GeoCoverage:
    active_properties = int(
        session.scalar(
            select(func.count()).select_from(Property).where(Property.status == ListingStatus.ACTIVE)
        )
        or 0
    )
    located_properties = int(
        session.scalar(
            select(func.count())
            .select_from(Property)
            .where(Property.status == ListingStatus.ACTIVE, Property.location.is_not(None))
        )
        or 0
    )

    jobs = relevant_active_jobs(session)
    job_ids = {job.id for job in jobs}
    if not job_ids:
        return GeoCoverage(
            active_properties=active_properties,
            located_properties=located_properties,
            relevant_jobs=0,
            relevant_job_locations=0,
            located_job_locations=0,
            jobs_with_located_location=0,
        )

    relevant_job_locations = int(
        session.scalar(
            select(func.count()).select_from(JobLocation).where(JobLocation.job_id.in_(job_ids))
        )
        or 0
    )
    located_job_locations = int(
        session.scalar(
            select(func.count())
            .select_from(JobLocation)
            .where(JobLocation.job_id.in_(job_ids), JobLocation.location.is_not(None))
        )
        or 0
    )
    jobs_with_located_location = int(
        session.scalar(
            select(func.count(func.distinct(JobLocation.job_id))).where(
                JobLocation.job_id.in_(job_ids),
                JobLocation.location.is_not(None),
            )
        )
        or 0
    )

    return GeoCoverage(
        active_properties=active_properties,
        located_properties=located_properties,
        relevant_jobs=len(jobs),
        relevant_job_locations=relevant_job_locations,
        located_job_locations=located_job_locations,
        jobs_with_located_location=jobs_with_located_location,
    )


def load_spatial_candidate_matches(
    session: Session,
    *,
    profile_slug: str = PROFILE_SLUG,
    radius_km: float = 50.0,
    job_limit: int = 10,
    properties_per_job: int = 5,
) -> list[SpatialJobMatch]:
    """Pair the best current intrinsic-fit jobs with nearby active properties.

    Candidate curation and fit remain separate from geography: hidden and hard-incompatible
    jobs are excluded, while favorite status does not change intrinsic score ordering.
    No NxM pair table is created; each selected job uses an indexed radius query on demand.
    """

    if job_limit <= 0:
        raise ValueError("job_limit must be greater than zero")
    if properties_per_job <= 0:
        raise ValueError("properties_per_job must be greater than zero")

    eligible = [
        row
        for row in load_live_job_fit(session, profile_slug=profile_slug)
        if not row.hidden
        and row.result.score is not None
        and not row.result.hard_constraints
    ]
    eligible.sort(
        key=lambda row: (
            -(row.result.score or 0),
            -row.result.preference_coverage,
            row.job.id,
        )
    )

    return [
        SpatialJobMatch(
            fit=row,
            properties=tuple(
                nearest_properties_for_job(
                    session,
                    row.job.id,
                    radius_km,
                    limit=properties_per_job,
                )
            ),
        )
        for row in eligible[:job_limit]
    ]
