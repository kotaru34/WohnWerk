from __future__ import annotations

from sqlalchemy import select

from app.crawling.coverage import ShardOutcome, summarize_shards
from app.database import SessionLocal
from app.models import (
    CoverageStatus,
    CrawlMode,
    CrawlRun,
    CrawlShardRun,
    RunStatus,
    Source,
)


def _stored_coverage_ok(shard: CrawlShardRun) -> tuple[bool, str]:
    cursor = shard.next_cursor or {}
    cards = cursor.get("discovery_cards_seen")
    parsed = cursor.get("discovery_cards_parsed")
    traversal = cursor.get("discovery_traversal_complete")
    delta = cursor.get("discovery_count_delta")
    tolerance = cursor.get("discovery_count_tolerance")

    if shard.status != RunStatus.SUCCESS:
        return False, f"status={shard.status}"
    if shard.result_cap_hit:
        return False, "result cap hit"
    if traversal is not True:
        return False, f"traversal={traversal!r}"
    if not isinstance(cards, int) or not isinstance(parsed, int) or cards != parsed:
        return False, f"cards={cards!r} parsed={parsed!r}"
    if not isinstance(delta, int) or not isinstance(tolerance, int) or abs(delta) > tolerance:
        return False, f"delta={delta!r} tolerance={tolerance!r}"
    return True, "ok"


def main() -> None:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == "immmo.at"))
        if source is None:
            raise SystemExit("immmo.at source not found")

        run = session.scalar(
            select(CrawlRun)
            .where(
                CrawlRun.source_id == source.id,
                CrawlRun.mode == CrawlMode.RECONCILIATION,
            )
            .order_by(CrawlRun.started_at.desc())
            .limit(1)
        )
        if run is None:
            raise SystemExit("No IMMMO reconciliation run found")

        previous_ok = session.scalar(
            select(CrawlRun.id)
            .where(
                CrawlRun.source_id == source.id,
                CrawlRun.mode == CrawlMode.RECONCILIATION,
                CrawlRun.coverage_status == CoverageStatus.OK,
                CrawlRun.started_at < run.started_at,
            )
            .limit(1)
        )
        if previous_ok is not None:
            raise SystemExit(
                "Refusing historical reclassification after an earlier OK reconciliation; "
                "run a fresh reconciliation instead."
            )

        shard_runs = list(
            session.scalars(
                select(CrawlShardRun)
                .where(CrawlShardRun.crawl_run_id == run.id)
                .order_by(CrawlShardRun.id)
            )
        )
        if len(shard_runs) != run.shards_total:
            raise SystemExit(
                f"Run #{run.id} has {len(shard_runs)} shard rows, expected {run.shards_total}"
            )

        problems: list[str] = []
        for shard in shard_runs:
            ok, reason = _stored_coverage_ok(shard)
            if not ok:
                problems.append(f"shard_run={shard.id}: {reason}")

        if problems:
            print(f"Run #{run.id} cannot be safely reclassified:")
            for problem in problems:
                print(f"  {problem}")
            raise SystemExit(1)

        for shard in shard_runs:
            shard.coverage_complete = True

        outcomes = [
            ShardOutcome(
                status=shard.status,
                pages_fetched=shard.pages_fetched,
                items_seen=shard.items_seen,
                items_new=shard.items_new,
                items_updated=shard.items_updated,
                source_reported_count=shard.source_reported_count,
                result_cap_hit=shard.result_cap_hit,
                coverage_complete=True,
            )
            for shard in shard_runs
        ]
        summary = summarize_shards(outcomes)
        if summary.coverage_status != CoverageStatus.OK:
            raise SystemExit(f"Unexpected recomputed coverage: {summary.coverage_status}")

        run.status = RunStatus.SUCCESS
        run.coverage_status = CoverageStatus.OK
        source.coverage_status = CoverageStatus.OK
        source.last_reconciliation_at = run.finished_at
        if source.last_success_at is None or (
            run.finished_at is not None and source.last_success_at < run.finished_at
        ):
            source.last_success_at = run.finished_at

        session.commit()
        print(
            f"Reclassified IMMMO Run #{run.id}: status={run.status} "
            f"coverage={run.coverage_status}; no listings were deactivated."
        )


if __name__ == "__main__":
    main()
