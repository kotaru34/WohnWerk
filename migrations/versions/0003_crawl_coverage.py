"""Add source sharding and crawl coverage tracking.

Revision ID: 0003_crawl_coverage
Revises: 0002_postal_centroid_metadata
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_crawl_coverage"
down_revision: str | None = "0002_postal_centroid_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column(
            "coverage_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
    )
    op.add_column("sources", sa.Column("last_incremental_at", sa.DateTime(timezone=True)))
    op.add_column("sources", sa.Column("last_reconciliation_at", sa.DateTime(timezone=True)))

    op.create_table(
        "source_shards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "cursor",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("result_cap", sa.Integer()),
        sa.Column("last_item_count", sa.Integer()),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_full_scan_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_id", "key", name="uq_source_shards_source_key"),
    )
    op.create_index("ix_source_shards_source_id", "source_shards", ["source_id"])
    op.create_index(
        "ix_source_shards_scheduler",
        "source_shards",
        ["source_id", "enabled", "priority"],
    )

    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'running'")),
        sa.Column(
            "coverage_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("shards_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("shards_completed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("shards_failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("items_seen", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("items_new", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("items_updated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("items_disappeared", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("source_reported_count", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.Column(
            "run_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_crawl_runs_source_id", "crawl_runs", ["source_id"])
    op.create_index("ix_crawl_runs_source_started", "crawl_runs", ["source_id", "started_at"])

    op.create_table(
        "crawl_shard_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("crawl_run_id", sa.Integer(), nullable=False),
        sa.Column("shard_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'running'")),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("items_seen", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("items_new", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("items_updated", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("source_reported_count", sa.Integer()),
        sa.Column("result_cap_hit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("coverage_complete", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "next_cursor",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text()),
        sa.ForeignKeyConstraint(["crawl_run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shard_id"], ["source_shards.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("crawl_run_id", "shard_id", name="uq_crawl_shard_runs_run_shard"),
    )
    op.create_index("ix_crawl_shard_runs_crawl_run_id", "crawl_shard_runs", ["crawl_run_id"])
    op.create_index("ix_crawl_shard_runs_shard_id", "crawl_shard_runs", ["shard_id"])
    op.create_index("ix_crawl_shard_runs_status", "crawl_shard_runs", ["crawl_run_id", "status"])

    op.add_column("property_listings", sa.Column("last_seen_crawl_run_id", sa.Integer()))
    op.create_foreign_key(
        "fk_property_listings_last_seen_crawl_run",
        "property_listings",
        "crawl_runs",
        ["last_seen_crawl_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_property_listings_last_seen_crawl_run_id",
        "property_listings",
        ["last_seen_crawl_run_id"],
    )

    op.add_column("job_listings", sa.Column("last_seen_crawl_run_id", sa.Integer()))
    op.create_foreign_key(
        "fk_job_listings_last_seen_crawl_run",
        "job_listings",
        "crawl_runs",
        ["last_seen_crawl_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_job_listings_last_seen_crawl_run_id",
        "job_listings",
        ["last_seen_crawl_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_listings_last_seen_crawl_run_id", table_name="job_listings")
    op.drop_constraint(
        "fk_job_listings_last_seen_crawl_run", "job_listings", type_="foreignkey"
    )
    op.drop_column("job_listings", "last_seen_crawl_run_id")

    op.drop_index("ix_property_listings_last_seen_crawl_run_id", table_name="property_listings")
    op.drop_constraint(
        "fk_property_listings_last_seen_crawl_run", "property_listings", type_="foreignkey"
    )
    op.drop_column("property_listings", "last_seen_crawl_run_id")

    op.drop_table("crawl_shard_runs")
    op.drop_table("crawl_runs")
    op.drop_table("source_shards")

    op.drop_column("sources", "last_reconciliation_at")
    op.drop_column("sources", "last_incremental_at")
    op.drop_column("sources", "coverage_status")
