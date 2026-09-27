"""Add profile-scoped house suitability policy.

Revision ID: 0013_candidate_house_policy
Revises: 0012_de_postal_codes
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_candidate_house_policy"
down_revision = "0012_de_postal_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_house_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "de_plz_blacklist",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
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
    op.create_index(
        "ix_candidate_house_policies_profile_id",
        "candidate_house_policies",
        ["profile_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_house_policies_profile_id",
        table_name="candidate_house_policies",
    )
    op.drop_table("candidate_house_policies")
