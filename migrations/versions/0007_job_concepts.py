"""Add normalized job concept vocabulary and evidence tables.

Revision ID: 0007_job_concepts
Revises: 0006_job_source_tenants
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_job_concepts"
down_revision: str | None = "0006_job_source_tenants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_concepts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("label_de", sa.String(length=240), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.UniqueConstraint("kind", "slug", name="uq_job_concepts_kind_slug"),
    )
    op.create_index(
        "ix_job_concepts_kind_enabled",
        "job_concepts",
        ["kind", "enabled"],
    )

    op.create_table(
        "job_concept_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "concept_id",
            sa.Integer(),
            sa.ForeignKey("job_concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias", sa.String(length=240), nullable=False),
        sa.Column("normalized_alias", sa.String(length=240), nullable=False),
        sa.Column("language", sa.String(length=8)),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="seed"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
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
            "concept_id",
            "normalized_alias",
            name="uq_job_concept_aliases_concept_normalized",
        ),
    )
    op.create_index(
        "ix_job_concept_aliases_concept_id",
        "job_concept_aliases",
        ["concept_id"],
    )
    op.create_index(
        "ix_job_concept_aliases_enabled",
        "job_concept_aliases",
        ["enabled"],
    )

    op.create_table(
        "job_concept_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "concept_id",
            sa.Integer(),
            sa.ForeignKey("job_concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "alias_id",
            sa.Integer(),
            sa.ForeignKey("job_concept_aliases.id", ondelete="SET NULL"),
        ),
        sa.Column("field", sa.String(length=24), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("matched_text", sa.String(length=240), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("extractor_version", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "job_id",
            "concept_id",
            "field",
            "extractor_version",
            name="uq_job_concept_evidence_job_concept_field_version",
        ),
    )
    op.create_index("ix_job_concept_evidence_job_id", "job_concept_evidence", ["job_id"])
    op.create_index(
        "ix_job_concept_evidence_concept_id",
        "job_concept_evidence",
        ["concept_id"],
    )
    op.create_index(
        "ix_job_concept_evidence_alias_id",
        "job_concept_evidence",
        ["alias_id"],
    )
    op.create_index(
        "ix_job_concept_evidence_job_version",
        "job_concept_evidence",
        ["job_id", "extractor_version"],
    )
    op.create_index(
        "ix_job_concept_evidence_concept",
        "job_concept_evidence",
        ["concept_id"],
    )
    op.create_index(
        "ix_job_concept_evidence_scope",
        "job_concept_evidence",
        ["scope"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_concept_evidence_scope", table_name="job_concept_evidence")
    op.drop_index("ix_job_concept_evidence_concept", table_name="job_concept_evidence")
    op.drop_index("ix_job_concept_evidence_job_version", table_name="job_concept_evidence")
    op.drop_index("ix_job_concept_evidence_alias_id", table_name="job_concept_evidence")
    op.drop_index("ix_job_concept_evidence_concept_id", table_name="job_concept_evidence")
    op.drop_index("ix_job_concept_evidence_job_id", table_name="job_concept_evidence")
    op.drop_table("job_concept_evidence")
    op.drop_index("ix_job_concept_aliases_enabled", table_name="job_concept_aliases")
    op.drop_index("ix_job_concept_aliases_concept_id", table_name="job_concept_aliases")
    op.drop_table("job_concept_aliases")
    op.drop_index("ix_job_concepts_kind_enabled", table_name="job_concepts")
    op.drop_table("job_concepts")
