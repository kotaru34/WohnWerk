"""Add postal centroid provenance metadata.

Revision ID: 0002_postal_centroid_metadata
Revises: 0001_initial
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_postal_centroid_metadata"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("postal_codes", sa.Column("location_source", sa.String(length=120)))
    op.add_column("postal_codes", sa.Column("location_method", sa.String(length=40)))
    op.add_column("postal_codes", sa.Column("location_sample_count", sa.Integer()))


def downgrade() -> None:
    op.drop_column("postal_codes", "location_sample_count")
    op.drop_column("postal_codes", "location_method")
    op.drop_column("postal_codes", "location_source")
