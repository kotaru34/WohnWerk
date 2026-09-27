"""Add source-backed property Internet evidence.

Revision ID: 0017_internet_source_evidence
Revises: 0016_internet_access
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_internet_source_evidence"
down_revision = "0016_internet_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "property_internet_source_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_listing_id",
            sa.Integer(),
            sa.ForeignKey("property_listings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("evidence_key", sa.String(length=80), nullable=False),
        sa.Column("evidence_kind", sa.String(length=40), nullable=False),
        sa.Column("availability_status", sa.String(length=32)),
        sa.Column("claim_semantics", sa.String(length=48)),
        sa.Column("provider_name", sa.String(length=120)),
        sa.Column("technology", sa.String(length=48)),
        sa.Column("max_download_mbps", sa.Integer()),
        sa.Column("max_upload_mbps", sa.Integer()),
        sa.Column("source_address", sa.String(length=500)),
        sa.Column("address_precision", sa.String(length=48)),
        sa.Column("evidence_text", sa.Text()),
        sa.Column(
            "normalized_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source_url", sa.String(length=1200), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "property_listing_id",
            "evidence_key",
            name="uq_property_internet_source_evidence_listing_key",
        ),
    )
    op.create_index(
        "ix_property_internet_source_evidence_property_id",
        "property_internet_source_evidence",
        ["property_id"],
    )
    op.create_index(
        "ix_property_internet_source_evidence_property_listing_id",
        "property_internet_source_evidence",
        ["property_listing_id"],
    )
    op.create_index(
        "ix_property_internet_source_evidence_property_kind",
        "property_internet_source_evidence",
        ["property_id", "evidence_kind"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_property_internet_source_evidence_property_kind",
        table_name="property_internet_source_evidence",
    )
    op.drop_index(
        "ix_property_internet_source_evidence_property_listing_id",
        table_name="property_internet_source_evidence",
    )
    op.drop_index(
        "ix_property_internet_source_evidence_property_id",
        table_name="property_internet_source_evidence",
    )
    op.drop_table("property_internet_source_evidence")
