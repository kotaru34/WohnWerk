"""Add candidate-specific job curation state.

Revision ID: 0009_candidate_job_preferences
Revises: 0008_candidate_preferences
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_candidate_job_preferences"
down_revision = "0008_candidate_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_job_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
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
            "job_id",
            name="uq_candidate_job_preference_profile_job",
        ),
    )
    op.create_index(
        "ix_candidate_job_preferences_profile_id",
        "candidate_job_preferences",
        ["profile_id"],
    )
    op.create_index(
        "ix_candidate_job_preferences_job_id",
        "candidate_job_preferences",
        ["job_id"],
    )
    op.create_index(
        "ix_candidate_job_preferences_profile_hidden",
        "candidate_job_preferences",
        ["profile_id", "hidden"],
    )
    op.create_index(
        "ix_candidate_job_preferences_profile_favorite",
        "candidate_job_preferences",
        ["profile_id", "favorite"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_job_preferences_profile_favorite",
        table_name="candidate_job_preferences",
    )
    op.drop_index(
        "ix_candidate_job_preferences_profile_hidden",
        table_name="candidate_job_preferences",
    )
    op.drop_index("ix_candidate_job_preferences_job_id", table_name="candidate_job_preferences")
    op.drop_index(
        "ix_candidate_job_preferences_profile_id",
        table_name="candidate_job_preferences",
    )
    op.drop_table("candidate_job_preferences")
