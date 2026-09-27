"""Add Internet-access evidence and property location provenance.

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
    op.add_column("properties", sa.Column("location_source", sa.String(length=160)))
    op.add_column("properties", sa.Column("location_method", sa.String(length=80)))

    op.execute(
        """
        UPDATE properties AS p
        SET location_source = pc.location_source,
            location_method = pc.location_method
        FROM postal_codes AS pc
        WHERE p.postal_code = pc.postal_code
          AND p.location IS NOT NULL
          AND p.location_source IS NULL
          AND p.location_method IS NULL
        """
    )

    op.add_column(
        "candidate_house_policies",
        sa.Column("min_internet_download_mbps", sa.Integer()),
    )

    op.create_table(
        "internet_dataset_states",
        sa.Column("source_name", sa.String(length=80), primary_key=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("dataset_date", sa.Date(), nullable=False),
        sa.Column("coverage_status", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.String(length=1200), nullable=False),
        sa.Column("source_row_count", sa.Integer(), nullable=False),
        sa.Column("evidence_precision", sa.String(length=40), nullable=False),
        sa.Column("attribution", sa.String(length=500)),
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
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("dataset_date", sa.Date(), nullable=False),
        sa.Column("source_cell_id", sa.String(length=32), nullable=False),
        sa.Column("evidence_precision", sa.String(length=40), nullable=False),
        sa.Column("location_method", sa.String(length=80), nullable=False),
        sa.Column("max_any_download_mbps", sa.Integer()),
        sa.Column("max_any_coverage_percent", sa.Numeric(precision=7, scale=4)),
        sa.Column("max_full_download_mbps", sa.Integer()),
        sa.Column(
            "coverage_by_speed",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "technology_coverage_by_speed",
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
        "ix_property_internet_evidence_country_source",
        "property_internet_evidence",
        ["country_code", "source_name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_property_internet_evidence_country_source",
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
    op.drop_column("candidate_house_policies", "min_internet_download_mbps")
    op.drop_column("properties", "location_method")
    op.drop_column("properties", "location_source")
