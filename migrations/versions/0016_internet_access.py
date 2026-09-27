"""Add source-backed Internet access evidence and property location provenance.

Revision ID: 0016_internet_access
Revises: 0015_hospital_access
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_internet_access"
down_revision = "0015_hospital_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("location_source", sa.String(length=120)))
    op.add_column("properties", sa.Column("location_method", sa.String(length=40)))
    op.execute(
        """
        UPDATE properties AS p
        SET location_source = pc.location_source,
            location_method = pc.location_method
        FROM postal_codes AS pc
        WHERE p.postal_code = pc.postal_code
          AND p.location IS NOT NULL
        """
    )

    op.create_table(
        "internet_dataset_states",
        sa.Column("source_name", sa.String(length=80), primary_key=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("dataset_date", sa.Date(), nullable=False),
        sa.Column("coverage_status", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.String(length=1200), nullable=False),
        sa.Column("attribution", sa.String(length=300), nullable=False),
        sa.Column("local_path", sa.String(length=1200), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_internet_dataset_states_country_code",
        "internet_dataset_states",
        ["country_code"],
    )

    op.create_table(
        "property_internet_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_name",
            sa.String(length=80),
            sa.ForeignKey("internet_dataset_states.source_name", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dataset_date", sa.Date(), nullable=False),
        sa.Column("raster_id", sa.String(length=32), nullable=False),
        sa.Column("municipality_ags", sa.String(length=16)),
        sa.Column("evidence_precision", sa.String(length=40), nullable=False),
        sa.Column("lookup_location_method", sa.String(length=40), nullable=False),
        sa.Column("max_grid_mbps", sa.Integer()),
        sa.Column("max_full_coverage_mbps", sa.Integer()),
        sa.Column(
            "coverage_by_speed",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "coverage_by_technology",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "property_id",
            "source_name",
            name="uq_property_internet_evidence_property_source",
        ),
    )
    op.create_index(
        "ix_property_internet_evidence_property_id",
        "property_internet_evidence",
        ["property_id"],
    )
    op.create_index(
        "ix_property_internet_evidence_source_raster",
        "property_internet_evidence",
        ["source_name", "raster_id"],
    )

    op.add_column(
        "candidate_house_policies",
        sa.Column("minimum_fixed_internet_mbps", sa.Integer()),
    )


def downgrade() -> None:
    op.drop_column("candidate_house_policies", "minimum_fixed_internet_mbps")
    op.drop_index(
        "ix_property_internet_evidence_source_raster",
        table_name="property_internet_evidence",
    )
    op.drop_index(
        "ix_property_internet_evidence_property_id",
        table_name="property_internet_evidence",
    )
    op.drop_table("property_internet_evidence")
    op.drop_index(
        "ix_internet_dataset_states_country_code",
        table_name="internet_dataset_states",
    )
    op.drop_table("internet_dataset_states")
    op.drop_column("properties", "location_method")
    op.drop_column("properties", "location_source")
