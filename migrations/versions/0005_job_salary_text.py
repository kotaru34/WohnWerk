"""Allow full advertised salary text without arbitrary truncation.

Revision ID: 0005_job_salary_text
Revises: 0004_job_salary_dimensions
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_job_salary_text"
down_revision: str | None = "0004_job_salary_dimensions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "jobs",
        "salary_text",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Downgrading can fail if a stored salary text is longer than 500 characters;
    # this is intentionally explicit rather than silently truncating source data.
    op.alter_column(
        "jobs",
        "salary_text",
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        existing_nullable=True,
    )
