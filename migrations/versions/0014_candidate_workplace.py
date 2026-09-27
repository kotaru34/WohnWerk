"""Add profile-scoped candidate workplace.

Revision ID: 0014_candidate_workplace
Revises: 0013_candidate_house_policy
"""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography

revision = "0014_candidate_workplace"
down_revision = "0013_candidate_house_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_workplaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("input_text", sa.String(length=500), nullable=False),
        sa.Column("postal_code", sa.String(length=5)),
        sa.Column("city", sa.String(length=160)),
        sa.Column(
            "location",
            Geography(
                geometry_type="POINT",
                srid=4326,
                spatial_index=True,
            ),
        ),
        sa.Column("resolution_source", sa.String(length=160)),
        sa.Column("resolution_method", sa.String(length=80)),
        sa.Column("resolution_error", sa.Text()),
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
        "ix_candidate_workplaces_profile_id",
        "candidate_workplaces",
        ["profile_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_workplaces_profile_id",
        table_name="candidate_workplaces",
    )
    op.drop_table("candidate_workplaces")
