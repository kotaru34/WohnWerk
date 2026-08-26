from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawling.coverage import (
    CoverageSummary,
    create_run,
    finalize_run,
    reconcile_missing_listings,
)
from app.crawling.shards import sync_source_shards
from app.ingestion.properties import ingest_properties
from app.models import CrawlMode, CrawlRun, CrawlShardRun, RunStatus, Source
from app.sources.base import PropertySource


async def run_property_source(
    session: Session,
    *,
    source: Source,
    adapter: PropertySource,
    reconciliation: bool = False,
) -> tuple[CrawlRun, CoverageSummary]:
    """Run all enabled shards sequentially and account for incomplete coverage."""
    specs = adapter.default_shards()
    shards = sync_source_shards(session, source, specs)
    specs_by_key = {spec.key: spec for spec in specs}
    mode = CrawlMode.RECONCILIATION if reconciliation else CrawlMode.INCREMENTAL
    run = create_run(session, source, mode)

    for shard in sorted(shards, key=lambda item: (item.priority, item.id)):
        spec = specs_by_key[shard.key]
        shard_run = session.scalar(
            select(CrawlShardRun).where(
                CrawlShardRun.crawl_run_id == run.id,
                CrawlShardRun.shard_id == shard.id,
            )
        )
        if shard_run is None:
            raise RuntimeError(f"Missing crawl shard run for {source.name}/{shard.key}")

        try:
            batch = await adapter.fetch_shard(
                spec,
                cursor=shard.cursor,
                reconciliation=reconciliation,
            )
            new_count, updated_count = ingest_properties(
                session,
                source=source,
                run=run,
                items=batch.items,
            )

            now = datetime.now(UTC)
            shard_run.status = RunStatus.SUCCESS
            shard_run.finished_at = now
            shard_run.pages_fetched = batch.pages_fetched
            shard_run.items_seen = len(batch.items)
            shard_run.items_new = new_count
            shard_run.items_updated = updated_count
            shard_run.source_reported_count = batch.source_reported_count
            shard_run.result_cap_hit = batch.result_cap_hit
            shard_run.coverage_complete = batch.coverage_complete
            shard_run.next_cursor = batch.next_cursor

            shard.cursor = batch.next_cursor
            shard.last_item_count = len(batch.items)
            shard.last_success_at = now
            shard.consecutive_failures = 0
            if reconciliation and batch.coverage_complete and not batch.result_cap_hit:
                shard.last_full_scan_at = now
        except Exception as exc:  # noqa: BLE001 - shard boundary must record arbitrary adapter failure
            shard_run.status = RunStatus.FAILED
            shard_run.finished_at = datetime.now(UTC)
            shard_run.coverage_complete = False
            shard_run.error = f"{type(exc).__name__}: {exc}"
            shard.consecutive_failures += 1

        session.commit()

    summary = finalize_run(session, run)
    if reconciliation:
        reconcile_missing_listings(session, run)
    return run, summary
