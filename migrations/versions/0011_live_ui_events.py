"""Add durable live UI event journal.

Revision ID: 0011_live_ui_events
Revises: 0010_property_activity
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_live_ui_events"
down_revision = "0010_property_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_ui_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column(
            "profile_id",
            sa.Integer(),
            sa.ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_live_ui_events_profile_id",
        "live_ui_events",
        ["profile_id"],
    )
    op.create_index(
        "ix_live_ui_events_topic_id",
        "live_ui_events",
        ["topic", "id"],
    )
    op.create_index(
        "ix_live_ui_events_created_at",
        "live_ui_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_live_ui_events_created_at", table_name="live_ui_events")
    op.drop_index("ix_live_ui_events_topic_id", table_name="live_ui_events")
    op.drop_index("ix_live_ui_events_profile_id", table_name="live_ui_events")
    op.drop_table("live_ui_events")
