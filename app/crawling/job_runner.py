from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawling.coverage import (
    CoverageSummary,
    create_run,
    finalize_run,
    reconcile_missing_listings,
)
from app.crawling.shards import sync_source_shards
from app.ingestion.jobs import ingest_jobs, record_rejected_job_sightings
from app.jobs.discovery import partition_job_candidates
from app.models import CrawlMode, CrawlRun, CrawlShardRun, RunStatus, Source, SourceShard
from app.sources.base import JobSource, RawJob, SourceFetchError


def _partition_with_diagnostics(
    items: list[RawJob],
    cursor: dict,
) -> tuple[list[RawJob], list[RawJob], dict]:
    accepted, rejected = partition_job_candidates(items)
    diagnostics = dict(cursor)
    diagnostics["job_candidates_fetched"] = len(items)
    diagnostics["job_candidates_accepted"] = len(accepted)
    diagnostics["job_candidates_rejected"] = len(rejected)
    return accepted, rejected, diagnostics


async def run_job_source(
    session: Session,
    *,
    source: Source,
    adapter: JobSource,
    reconciliation: bool = False,
) -> tuple[CrawlRun, CoverageSummary]:
    """Run enabled job shards with coverage and relevance kept as separate states."""
    specs = adapter.default_shards()
    shards = sync_source_shards(session, source, specs)
    specs_by_key = {spec.key: spec for spec in specs}
    mode = CrawlMode.RECONCILIATION if reconciliation else CrawlMode.INCREMENTAL
    run = create_run(session, source, mode)
    source_id = source.id
    run_id = run.id

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

        shard_id = shard.id
        shard_run_id = shard_run.id

        try:
            batch = await adapter.fetch_shard(
                spec,
                cursor=shard.cursor,
                reconciliation=reconciliation,
            )
            candidate_items, rejected_items, next_cursor = _partition_with_diagnostics(
                batch.items,
                batch.next_cursor,
            )
            new_count, updated_count = ingest_jobs(
                session,
                source=source,
                run=run,
                items=candidate_items,
            )
            rejected_existing_seen, rejected_reactivated = record_rejected_job_sightings(
                session,
                source=source,
                run=run,
                items=rejected_items,
            )
            next_cursor["job_rejected_existing_seen"] = rejected_existing_seen
            next_cursor["job_rejected_reactivated"] = rejected_reactivated

            now = datetime.now(UTC)
            shard_run.status = RunStatus.SUCCESS
            shard_run.finished_at = now
            shard_run.pages_fetched = batch.pages_fetched
            # `items_seen` intentionally remains the durable relevant-corpus count.
            # Source-lifecycle sightings for rejected persisted listings are recorded
            # separately in next_cursor diagnostics and last_seen_crawl_run_id.
            shard_run.items_seen = len(candidate_items)
            shard_run.items_new = new_count
            shard_run.items_updated = updated_count
            shard_run.source_reported_count = batch.source_reported_count
            shard_run.result_cap_hit = batch.result_cap_hit
            shard_run.coverage_complete = batch.coverage_complete
            shard_run.next_cursor = next_cursor

            shard.cursor = next_cursor
            shard.last_item_count = len(candidate_items)
            shard.last_success_at = now
            shard.consecutive_failures = 0
            if reconciliation and batch.coverage_complete and not batch.result_cap_hit:
                shard.last_full_scan_at = now
        except Exception as exc:
            session.rollback()
            partial_new = 0
            partial_updated = 0
            partial_items_seen = 0
            partial_cursor: dict = {}
            if isinstance(exc, SourceFetchError) and exc.partial_items:
                partial_source = session.get(Source, source_id)
                partial_run = session.get(CrawlRun, run_id)
                if partial_source is None or partial_run is None:
                    raise RuntimeError(
                        f"Could not reload partial-run state for {source.name}/{spec.key}"
                    ) from exc
                candidate_items, rejected_items, partial_cursor = _partition_with_diagnostics(
                    cast(list[RawJob], exc.partial_items),
                    exc.next_cursor,
                )
                partial_items_seen = len(candidate_items)
                partial_new, partial_updated = ingest_jobs(
                    session,
                    source=partial_source,
                    run=partial_run,
                    items=candidate_items,
                )
                rejected_existing_seen, rejected_reactivated = record_rejected_job_sightings(
                    session,
                    source=partial_source,
                    run=partial_run,
                    items=rejected_items,
                )
                partial_cursor["job_rejected_existing_seen"] = rejected_existing_seen
                partial_cursor["job_rejected_reactivated"] = rejected_reactivated

            failed_shard_run = session.get(CrawlShardRun, shard_run_id)
            failed_shard = session.get(SourceShard, shard_id)
            if failed_shard_run is None or failed_shard is None:
                raise RuntimeError(
                    f"Could not reload failed shard state for {source.name}/{spec.key}"
                ) from exc

            failed_shard_run.status = RunStatus.FAILED
            failed_shard_run.finished_at = datetime.now(UTC)
            failed_shard_run.coverage_complete = False
            failed_shard_run.error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, SourceFetchError):
                failed_shard_run.pages_fetched = exc.pages_fetched
                failed_shard_run.items_seen = partial_items_seen
                failed_shard_run.items_new = partial_new
                failed_shard_run.items_updated = partial_updated
                failed_shard_run.source_reported_count = exc.source_reported_count
                failed_shard_run.next_cursor = partial_cursor or exc.next_cursor
            failed_shard.consecutive_failures += 1

        session.commit()

    summary = finalize_run(session, run)
    if reconciliation:
        reconcile_missing_listings(session, run)
    return run, summary
