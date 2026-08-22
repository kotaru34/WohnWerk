"""Create initial Austria-first WohnWerk schema.

Revision ID: 0001_initial
Revises: None
Create Date: 2026-08-22
"""

from collections.abc import Sequence

from alembic import op
from geoalchemy2 import Geography
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("adapter", sa.String(length=160), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "poll_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("360"),
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("name", name="uq_sources_name"),
    )

    op.create_table(
        "postal_codes",
        sa.Column("postal_code", sa.String(length=4), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "location",
            Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("source", sa.String(length=120), nullable=True),
    )
    op.create_index(
        "ix_postal_codes_location",
        "postal_codes",
        ["location"],
        unique=False,
        postgresql_using="gist",
    )

    op.create_table(
        "properties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_eur", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("living_area_m2", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("plot_area_m2", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("postal_code", sa.String(length=4), nullable=True),
        sa.Column("city", sa.String(length=160), nullable=True),
        sa.Column(
            "location",
            Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("canonical_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("inactive_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["postal_code"],
            ["postal_codes.postal_code"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("canonical_hash", name="uq_properties_canonical_hash"),
    )
    op.create_index("ix_properties_postal_code", "properties", ["postal_code"])
    op.create_index("ix_properties_city", "properties", ["city"])
    op.create_index(
        "ix_properties_location",
        "properties",
        ["location"],
        postgresql_using="gist",
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("company", sa.String(length=300), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("salary_min_eur_year", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("salary_max_eur_year", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("salary_text", sa.String(length=500), nullable=True),
        sa.Column("salary_is_minimum_only", sa.Boolean(), nullable=True),
        sa.Column("job_fit_score", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("canonical_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("inactive_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("canonical_hash", name="uq_jobs_canonical_hash"),
    )
    op.create_index("ix_jobs_title", "jobs", ["title"])
    op.create_index("ix_jobs_company", "jobs", ["company"])
    op.create_index("ix_jobs_job_fit_score", "jobs", ["job_fit_score"])

    op.create_table(
        "property_listings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_listing_id", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=1200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("inactive_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "source_id",
            "source_listing_id",
            name="uq_property_source_listing",
        ),
    )
    op.create_index("ix_property_listings_property_id", "property_listings", ["property_id"])
    op.create_index("ix_property_listings_source_id", "property_listings", ["source_id"])

    op.create_table(
        "job_listings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_listing_id", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=1200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("inactive_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_id", "source_listing_id", name="uq_job_source_listing"),
    )
    op.create_index("ix_job_listings_job_id", "job_listings", ["job_id"])
    op.create_index("ix_job_listings_source_id", "job_listings", ["source_id"])

    op.create_table(
        "job_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("postal_code", sa.String(length=4), nullable=True),
        sa.Column("city", sa.String(length=160), nullable=True),
        sa.Column("location_text", sa.String(length=500), nullable=True),
        sa.Column(
            "location",
            Geography(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("remote", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["postal_code"],
            ["postal_codes.postal_code"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_job_locations_job_id", "job_locations", ["job_id"])
    op.create_index("ix_job_locations_postal_code", "job_locations", ["postal_code"])
    op.create_index("ix_job_locations_city", "job_locations", ["city"])
    op.create_index(
        "ix_job_locations_job_postal_code",
        "job_locations",
        ["job_id", "postal_code"],
    )
    op.create_index(
        "ix_job_locations_location",
        "job_locations",
        ["location"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_table("job_locations")
    op.drop_table("job_listings")
    op.drop_table("property_listings")
    op.drop_table("jobs")
    op.drop_table("properties")
    op.drop_table("postal_codes")
    op.drop_table("sources")
