"""Allow German five-digit postal codes.

Revision ID: 0012_de_postal_codes
Revises: 0011_live_ui_events
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_de_postal_codes"
down_revision = "0011_live_ui_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # AT uses four digits; DE uses five.  Widen the shared reference and both
    # foreign-key columns without changing any matching semantics.
    op.alter_column(
        "postal_codes",
        "postal_code",
        existing_type=sa.String(length=4),
        type_=sa.String(length=5),
        existing_nullable=False,
    )
    op.alter_column(
        "properties",
        "postal_code",
        existing_type=sa.String(length=4),
        type_=sa.String(length=5),
        existing_nullable=True,
    )
    op.alter_column(
        "job_locations",
        "postal_code",
        existing_type=sa.String(length=4),
        type_=sa.String(length=5),
        existing_nullable=True,
    )


def downgrade() -> None:
    # This succeeds only when no five-digit DE values remain, which is exactly
    # what we want for a safe downgrade instead of silently truncating PLZs.
    op.alter_column(
        "job_locations",
        "postal_code",
        existing_type=sa.String(length=5),
        type_=sa.String(length=4),
        existing_nullable=True,
    )
    op.alter_column(
        "properties",
        "postal_code",
        existing_type=sa.String(length=5),
        type_=sa.String(length=4),
        existing_nullable=True,
    )
    op.alter_column(
        "postal_codes",
        "postal_code",
        existing_type=sa.String(length=5),
        type_=sa.String(length=4),
        existing_nullable=False,
    )
