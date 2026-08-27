"""Preserve original job salary dimensions.

Revision ID: 0004_job_salary_dimensions
Revises: 0003_crawl_coverage
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_job_salary_dimensions"
down_revision: str | None = "0003_crawl_coverage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("salary_min", sa.Numeric(12, 2)))
    op.add_column("jobs", sa.Column("salary_max", sa.Numeric(12, 2)))
    op.add_column("jobs", sa.Column("salary_currency", sa.String(length=3)))
    op.add_column("jobs", sa.Column("salary_period", sa.String(length=20)))
    op.add_column("jobs", sa.Column("salary_payment_count", sa.Integer()))
    op.add_column("jobs", sa.Column("salary_provenance", sa.String(length=20)))
    op.add_column("jobs", sa.Column("salary_confidence", sa.Numeric(4, 3)))


def downgrade() -> None:
    op.drop_column("jobs", "salary_confidence")
    op.drop_column("jobs", "salary_provenance")
    op.drop_column("jobs", "salary_payment_count")
    op.drop_column("jobs", "salary_period")
    op.drop_column("jobs", "salary_currency")
    op.drop_column("jobs", "salary_max")
    op.drop_column("jobs", "salary_min")
