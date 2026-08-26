from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from geoalchemy2 import Geography
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SourceCategory(StrEnum):
    PROPERTY = "property"
    JOB = "job"


class ListingStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    adapter: Mapped[str] = mapped_column(String(160), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=360, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PostalCode(Base):
    """Austrian postal-code reference data.

    Austrian postal codes are four digits. `location` represents an approximate
    centroid and is intentionally not treated as a street-accurate coordinate.
    """

    __tablename__ = "postal_codes"

    postal_code: Mapped[str] = mapped_column(String(4), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    location: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True)
    )
    source: Mapped[str | None] = mapped_column(String(120))
    location_source: Mapped[str | None] = mapped_column(String(120))
    location_method: Mapped[str | None] = mapped_column(String(40))
    location_sample_count: Mapped[int | None] = mapped_column(Integer)


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    price_eur: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    living_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    plot_area_m2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    postal_code: Mapped[str | None] = mapped_column(
        ForeignKey("postal_codes.postal_code", ondelete="SET NULL"), index=True
    )
    city: Mapped[str | None] = mapped_column(String(160), index=True)
    location: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True)
    )
    status: Mapped[str] = mapped_column(String(20), default=ListingStatus.ACTIVE, nullable=False)
    canonical_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    inactive_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    listings: Mapped[list[PropertyListing]] = relationship(
        back_populates="property", cascade="all, delete-orphan"
    )


class PropertyListing(Base):
    __tablename__ = "property_listings"
    __table_args__ = (
        UniqueConstraint("source_id", "source_listing_id", name="uq_property_source_listing"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_listing_id: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=ListingStatus.ACTIVE, nullable=False)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    inactive_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    property: Mapped[Property] = relationship(back_populates="listings")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    company: Mapped[str | None] = mapped_column(String(300), index=True)
    description: Mapped[str | None] = mapped_column(Text)

    # Normalized gross annual figures when the source data allows normalization.
    salary_min_eur_year: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_max_eur_year: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_text: Mapped[str | None] = mapped_column(String(500))
    salary_is_minimum_only: Mapped[bool | None] = mapped_column(Boolean)

    job_fit_score: Mapped[int | None] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(20), default=ListingStatus.ACTIVE, nullable=False)
    canonical_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    inactive_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    listings: Mapped[list[JobListing]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    locations: Mapped[list[JobLocation]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobListing(Base):
    __tablename__ = "job_listings"
    __table_args__ = (
        UniqueConstraint("source_id", "source_listing_id", name="uq_job_source_listing"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_listing_id: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=ListingStatus.ACTIVE, nullable=False)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    inactive_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[Job] = relationship(back_populates="listings")


class JobLocation(Base):
    __tablename__ = "job_locations"
    __table_args__ = (
        Index("ix_job_locations_job_postal_code", "job_id", "postal_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    postal_code: Mapped[str | None] = mapped_column(
        ForeignKey("postal_codes.postal_code", ondelete="SET NULL"), index=True
    )
    city: Mapped[str | None] = mapped_column(String(160), index=True)
    location_text: Mapped[str | None] = mapped_column(String(500))
    location: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True)
    )
    remote: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    job: Mapped[Job] = relationship(back_populates="locations")
