from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import Job, JobLocation, ListingStatus, Property


def radius_metres(radius_km: float) -> float:
    if radius_km <= 0:
        raise ValueError("radius_km must be greater than zero")
    return radius_km * 1000.0


def job_locations_near_property_stmt(
    property_id: int,
    radius_km: float,
    *,
    minimum_job_fit_score: int | None = None,
) -> Select:
    """Build a PostGIS query for job locations near one property.

    Distances are calculated on `geography` points, so PostGIS returns metres.
    A canonical job can have several matching locations; caller/UI logic may select
    the nearest location per job when presenting results.
    """

    property_location = (
        select(Property.location).where(Property.id == property_id).scalar_subquery()
    )
    distance_km = (
        func.ST_Distance(JobLocation.location, property_location) / 1000.0
    ).label("distance_km")

    stmt = (
        select(Job, JobLocation, distance_km)
        .join(JobLocation, JobLocation.job_id == Job.id)
        .where(
            Job.status == ListingStatus.ACTIVE,
            JobLocation.location.is_not(None),
            func.ST_DWithin(
                JobLocation.location,
                property_location,
                radius_metres(radius_km),
            ),
        )
        .order_by(distance_km.asc())
    )

    if minimum_job_fit_score is not None:
        stmt = stmt.where(Job.job_fit_score >= minimum_job_fit_score)

    return stmt


def properties_near_job_location_stmt(job_location_id: int, radius_km: float) -> Select:
    """Build the inverse PostGIS query: houses near one concrete job location."""

    job_location = (
        select(JobLocation.location)
        .where(JobLocation.id == job_location_id)
        .scalar_subquery()
    )
    distance_km = (
        func.ST_Distance(Property.location, job_location) / 1000.0
    ).label("distance_km")

    return (
        select(Property, distance_km)
        .where(
            Property.status == ListingStatus.ACTIVE,
            Property.location.is_not(None),
            func.ST_DWithin(
                Property.location,
                job_location,
                radius_metres(radius_km),
            ),
        )
        .order_by(distance_km.asc())
    )


def job_locations_near_property(
    db: Session,
    property_id: int,
    radius_km: float,
    *,
    minimum_job_fit_score: int | None = None,
):
    return db.execute(
        job_locations_near_property_stmt(
            property_id,
            radius_km,
            minimum_job_fit_score=minimum_job_fit_score,
        )
    ).all()


def properties_near_job_location(db: Session, job_location_id: int, radius_km: float):
    return db.execute(properties_near_job_location_stmt(job_location_id, radius_km)).all()
