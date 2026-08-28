"""Add candidate profiles and four-state concept preferences.

Revision ID: 0008_candidate_preferences
Revises: 0007_job_concepts
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_candidate_preferences"
down_revision: str | None = "0007_job_concepts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=120), nullable=False, unique=True),
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
    )
    op.create_index("ix_candidate_profiles_enabled", "candidate_profiles", ["enabled"])

    op.create_table(
        "candidate_concept_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "concept_id",
            sa.Integer(),
            sa.ForeignKey("job_concepts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("seed_version", sa.String(length=80)),
        sa.Column("note", sa.Text()),
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
            "profile_id",
            "concept_id",
            name="uq_candidate_preference_profile_concept",
        ),
        sa.CheckConstraint(
            "state IN ('can_want', 'can_not_want', 'cannot_want', 'cannot_not_want')",
            name="ck_candidate_preference_state",
        ),
        sa.CheckConstraint(
            "source IN ('seed', 'manual')",
            name="ck_candidate_preference_source",
        ),
    )
    op.create_index(
        "ix_candidate_concept_preferences_profile_id",
        "candidate_concept_preferences",
        ["profile_id"],
    )
    op.create_index(
        "ix_candidate_concept_preferences_concept_id",
        "candidate_concept_preferences",
        ["concept_id"],
    )
    op.create_index(
        "ix_candidate_preferences_profile_state",
        "candidate_concept_preferences",
        ["profile_id", "state"],
    )
    op.create_index(
        "ix_candidate_preferences_profile_source",
        "candidate_concept_preferences",
        ["profile_id", "source"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_preferences_profile_source",
        table_name="candidate_concept_preferences",
    )
    op.drop_index(
        "ix_candidate_preferences_profile_state",
        table_name="candidate_concept_preferences",
    )
    op.drop_index(
        "ix_candidate_concept_preferences_concept_id",
        table_name="candidate_concept_preferences",
    )
    op.drop_index(
        "ix_candidate_concept_preferences_profile_id",
        table_name="candidate_concept_preferences",
    )
    op.drop_table("candidate_concept_preferences")
    op.drop_index("ix_candidate_profiles_enabled", table_name="candidate_profiles")
    op.drop_table("candidate_profiles")
