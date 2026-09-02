from __future__ import annotations

import argparse
import math

from sqlalchemy import select

from app.crawling.coverage import finalize_run, reconcile_missing_listings
from app.database import SessionLocal
from app.ingestion.immmo_continuity import reconcile_immmo_continuity
from app.models import CoverageStatus, CrawlMode, CrawlRun, CrawlShardRun, RunStatus, Source
from app.sources.property.thumbnail_capture import IMMMO_SYNTHETIC_RATE_LIMIT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Re-evaluate one completed degraded IMMMO reconciliation using the current "
            "coverage policy without fetching the same search pages again."
        )
    )
    parser.add_argument("run_id", type=int)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _int(cursor: dict, key: str) -> int:
    try:
        return int(cursor.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        run = session.get(CrawlRun, args.run_id)
        if run is None:
            raise SystemExit(f"run {args.run_id} not found")
        source = session.get(Source, run.source_id)
        if source is None or source.name != "immmo.at":
            raise SystemExit("run is not IMMMO")
        if run.mode != CrawlMode.RECONCILIATION:
            raise SystemExit("run is not a reconciliation")
        if run.coverage_status == CoverageStatus.OK:
            print(f"run={run.id} coverage=ok already_authoritative=true")
            return
        if run.status == RunStatus.FAILED:
            raise SystemExit("failed runs cannot be promoted")

        shard_runs = list(
            session.scalars(
                select(CrawlShardRun)
                .where(CrawlShardRun.crawl_run_id == run.id)
                .order_by(CrawlShardRun.id)
            )
        )
        if not shard_runs:
            raise SystemExit("run has no shard rows")

        promotable = True
        print(
            f"run={run.id} status={run.status} coverage={run.coverage_status} "
            f"shards={len(shard_runs)}"
        )
        for shard_run in shard_runs:
            cursor = dict(shard_run.next_cursor or {})
            cards = _int(cursor, "discovery_cards_seen")
            parsed = _int(cursor, "discovery_cards_parsed")
            synthetic = _int(cursor, "discovery_synthetic_cards")
            count_delta = _int(cursor, "discovery_count_delta")
            count_tolerance = _int(cursor, "discovery_count_tolerance")
            synthetic_tolerance = max(3, math.ceil(cards * IMMMO_SYNTHETIC_RATE_LIMIT))
            traversal = cursor.get("discovery_traversal_complete") is True
            link_quality = synthetic <= synthetic_tolerance
            ok = bool(
                shard_run.status == RunStatus.SUCCESS
                and not shard_run.result_cap_hit
                and traversal
                and cards > 0
                and cards == parsed
                and abs(count_delta) <= count_tolerance
                and link_quality
            )
            promotable = promotable and ok
            print(
                f"  shard_run={shard_run.id} ok={str(ok).lower()} "
                f"cards={cards} parsed={parsed} synthetic={synthetic} "
                f"synthetic_tolerance={synthetic_tolerance} "
                f"count_delta={count_delta}/{count_tolerance} traversal={traversal}"
            )

            if args.apply and ok:
                cursor["discovery_synthetic_tolerance"] = synthetic_tolerance
                cursor["discovery_link_quality_ok"] = True
                cursor["discovery_link_quality_rate_limit"] = IMMMO_SYNTHETIC_RATE_LIMIT
                shard_run.next_cursor = cursor
                shard_run.coverage_complete = True

        print(f"promotable={str(promotable).lower()}")
        if not promotable:
            raise SystemExit("run does not satisfy the current complete-coverage policy")
        if not args.apply:
            print("mode=dry-run no database changes")
            return

        session.commit()
        summary = finalize_run(session, run)
        if summary.coverage_status != CoverageStatus.OK:
            raise SystemExit(f"promotion did not produce coverage=ok: {summary.coverage_status}")

        continuity = reconcile_immmo_continuity(session, run)
        property_disappeared, job_disappeared = reconcile_missing_listings(session, run)
        print(f"status={summary.run_status} coverage={summary.coverage_status}")
        print(
            f"continuity_merged={continuity.matched} "
            f"new_rows_reclassified={continuity.new_rows_reclassified}"
        )
        print(
            f"disappeared_properties={property_disappeared} "
            f"disappeared_jobs={job_disappeared}"
        )
        print("mode=applied")


if __name__ == "__main__":
    main()
