"""Add DE Internet evidence, property location precision and profile threshold.

Revision ID: 0016_de_internet
Revises: 0015_hospital_access
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_de_internet"
down_revision = "0015_hospital_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("location_precision", sa.String(length=40)))
    op.create_index("ix_properties_location_precision", "properties", ["location_precision"])
    op.execute(
        "UPDATE properties "
        "SET location_precision = 'postal_centroid' "
        "WHERE location IS NOT NULL AND location_precision IS NULL"
    )

    op.create_table(
        "internet_dataset_states",
        sa.Column("source_name", sa.String(length=80), primary_key=True),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("dataset_date", sa.Date(), nullable=False),
        sa.Column("coverage_status", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.String(length=1200), nullable=False),
        sa.Column("attribution", sa.String(length=300), nullable=False),
        sa.Column("evidence_precision", sa.String(length=40), nullable=False),
        sa.Column("artifact_path", sa.String(length=1200)),
        sa.Column("artifact_sha256", sa.String(length=64)),
        sa.Column("feature_count", sa.Integer()),
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
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("source_name", sa.String(length=80), nullable=False),
        sa.Column("source_reference", sa.String(length=255), nullable=False),
        sa.Column("evidence_kind", sa.String(length=40), nullable=False),
        sa.Column("evidence_precision", sa.String(length=60), nullable=False),
        sa.Column("provider_name", sa.String(length=160)),
        sa.Column("availability_state", sa.String(length=20), nullable=False),
        sa.Column("max_download_mbps", sa.Integer()),
        sa.Column("technology", sa.String(length=80)),
        sa.Column("coverage_percent", sa.Numeric(precision=6, scale=3)),
        sa.Column("monthly_price_eur", sa.Numeric(precision=10, scale=2)),
        sa.Column("source_url", sa.String(length=1200), nullable=False),
        sa.Column("dataset_date", sa.Date()),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.UniqueConstraint(
            "property_id",
            "source_name",
            "source_reference",
            name="uq_property_internet_evidence_source_reference",
        ),
    )
    op.create_index(
        "ix_property_internet_evidence_property_id",
        "property_internet_evidence",
        ["property_id"],
    )
    op.create_index(
        "ix_property_internet_evidence_property_source",
        "property_internet_evidence",
        ["property_id", "source_name"],
    )

    op.add_column(
        "candidate_house_policies",
        sa.Column("min_fixed_internet_mbps", sa.Integer()),
    )


def downgrade() -> None:
    op.drop_column("candidate_house_policies", "min_fixed_internet_mbps")
    op.drop_index(
        "ix_property_internet_evidence_property_source",
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
    op.drop_index("ix_properties_location_precision", table_name="properties")
    op.drop_column("properties", "location_precision")
