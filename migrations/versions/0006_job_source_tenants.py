"""Add DB-backed job source tenant registry.

Revision ID: 0006_job_source_tenants
Revises: 0005_job_salary_text
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_job_source_tenants"
down_revision: str | None = "0005_job_salary_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_source_tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("namespace", sa.String(length=40), nullable=False, server_default="default"),
        sa.Column("tenant_key", sa.String(length=240), nullable=False),
        sa.Column("company", sa.String(length=300), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("discovered_at", sa.DateTime(timezone=True)),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "source_id",
            "namespace",
            "tenant_key",
            name="uq_job_source_tenants_source_namespace_key",
        ),
    )
    op.create_index(
        "ix_job_source_tenants_source_id",
        "job_source_tenants",
        ["source_id"],
    )
    op.create_index(
        "ix_job_source_tenants_enabled",
        "job_source_tenants",
        ["source_id", "enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_source_tenants_enabled", table_name="job_source_tenants")
    op.drop_index("ix_job_source_tenants_source_id", table_name="job_source_tenants")
    op.drop_table("job_source_tenants")
