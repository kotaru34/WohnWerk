"""Add property curation, usable area, local image cache and seen baseline.

Revision ID: 0010_property_curation_images_seen
Revises: 0009_candidate_job_preferences
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_property_curation_images_seen"
down_revision = "0009_candidate_job_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column("usable_area_m2", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "candidate_profiles",
        sa.Column(
            "novelty_started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "candidate_job_preferences",
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_candidate_job_preferences_profile_viewed",
        "candidate_job_preferences",
        ["profile_id", "viewed_at"],
    )

    op.create_table(
        "candidate_property_preferences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
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
            "property_id",
            name="uq_candidate_property_preference_profile_property",
        ),
    )
    op.create_index(
        "ix_candidate_property_preferences_profile_id",
        "candidate_property_preferences",
        ["profile_id"],
    )
    op.create_index(
        "ix_candidate_property_preferences_property_id",
        "candidate_property_preferences",
        ["property_id"],
    )
    op.create_index(
        "ix_candidate_property_preferences_profile_hidden",
        "candidate_property_preferences",
        ["profile_id", "hidden"],
    )
    op.create_index(
        "ix_candidate_property_preferences_profile_favorite",
        "candidate_property_preferences",
        ["profile_id", "favorite"],
    )
    op.create_index(
        "ix_candidate_property_preferences_profile_viewed",
        "candidate_property_preferences",
        ["profile_id", "viewed_at"],
    )

    op.create_table(
        "property_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "property_listing_id",
            sa.Integer(),
            sa.ForeignKey("property_listings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_image_url", sa.Text(), nullable=True),
        sa.Column("local_filename", sa.String(255), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
    op.create_index("ix_property_images_property_id", "property_images", ["property_id"])
    op.create_index(
        "ix_property_images_property_listing_id",
        "property_images",
        ["property_listing_id"],
    )
    op.create_index(
        "ix_property_images_retry",
        "property_images",
        ["status", "retry_after"],
    )


def downgrade() -> None:
    op.drop_index("ix_property_images_retry", table_name="property_images")
    op.drop_index("ix_property_images_property_listing_id", table_name="property_images")
    op.drop_index("ix_property_images_property_id", table_name="property_images")
    op.drop_table("property_images")

    op.drop_index(
        "ix_candidate_property_preferences_profile_viewed",
        table_name="candidate_property_preferences",
    )
    op.drop_index(
        "ix_candidate_property_preferences_profile_favorite",
        table_name="candidate_property_preferences",
    )
    op.drop_index(
        "ix_candidate_property_preferences_profile_hidden",
        table_name="candidate_property_preferences",
    )
    op.drop_index(
        "ix_candidate_property_preferences_property_id",
        table_name="candidate_property_preferences",
    )
    op.drop_index(
        "ix_candidate_property_preferences_profile_id",
        table_name="candidate_property_preferences",
    )
    op.drop_table("candidate_property_preferences")

    op.drop_index(
        "ix_candidate_job_preferences_profile_viewed",
        table_name="candidate_job_preferences",
    )
    op.drop_column("candidate_job_preferences", "viewed_at")
    op.drop_column("candidate_profiles", "novelty_started_at")
    op.drop_column("properties", "usable_area_m2")
