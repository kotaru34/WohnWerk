from __future__ import annotations

import argparse

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import CrawlRun, CrawlShardRun, PropertyListing, SourceShard


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Explain IMMMO reconciliation coverage diagnostics.")
    parser.add_argument("run_id", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        run = session.get(CrawlRun, args.run_id)
        if run is None:
            raise SystemExit(f"crawl run {args.run_id} not found")

        print(
            f"run={run.id} mode={run.mode} status={run.status} coverage={run.coverage_status} "
            f"seen={run.items_seen} new={run.items_new} updated={run.items_updated} "
            f"reported={run.source_reported_count} disappeared={run.items_disappeared}"
        )
        print("shards:")
        rows = session.execute(
            select(CrawlShardRun, SourceShard)
            .join(SourceShard, SourceShard.id == CrawlShardRun.shard_id)
            .where(CrawlShardRun.crawl_run_id == run.id)
            .order_by(SourceShard.key)
        )
        for shard_run, shard in rows:
            cursor = shard_run.next_cursor or {}
            print(
                f"  {shard.key}: coverage_complete={shard_run.coverage_complete} "
                f"seen={shard_run.items_seen} reported={shard_run.source_reported_count} "
                f"cards={cursor.get('discovery_cards_seen')} "
                f"synthetic={cursor.get('discovery_synthetic_cards')} "
                f"legacy_link_quality={cursor.get('discovery_link_quality_ok')} "
                f"structural={cursor.get('discovery_structural_coverage_ok')} "
                f"synthetic_new={cursor.get('discovery_synthetic_new')} "
                f"synthetic_new_tolerance={cursor.get('discovery_synthetic_new_tolerance')} "
                f"identity_churn={cursor.get('discovery_identity_churn_ok')} "
                f"policy={cursor.get('discovery_coverage_policy')} "
                f"count_delta={cursor.get('discovery_count_delta')} "
                f"count_tolerance={cursor.get('discovery_count_tolerance')} "
                f"thumbnails={cursor.get('thumbnail_urls_captured')}"
            )

        if run.finished_at is not None:
            synthetic_new = int(
                session.scalar(
                    select(func.count())
                    .select_from(PropertyListing)
                    .where(
                        PropertyListing.source_id == run.source_id,
                        PropertyListing.last_seen_crawl_run_id == run.id,
                        PropertyListing.first_seen_at >= run.started_at,
                        PropertyListing.first_seen_at <= run.finished_at,
                        PropertyListing.raw_payload.op("->>")("original_url_missing") == "true",
                    )
                )
                or 0
            )
            print(f"synthetic_new_in_run={synthetic_new}")


if __name__ == "__main__":
    main()
