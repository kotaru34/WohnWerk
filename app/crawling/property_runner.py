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
from app.crawling.immmo_quality import (
    annotate_immmo_coverage_cursor,
    decide_immmo_coverage,
    synthetic_new_in_shard,
)
from app.crawling.shards import sync_source_shards
from app.ingestion.immmo_continuity import reconcile_immmo_continuity
from app.ingestion.properties import ingest_properties
from app.models import CrawlMode, CrawlRun, CrawlShardRun, RunStatus, Source, SourceShard
from app.property_acquisition import annotate_property_items_by_budget
from app.property_liveness import prepare_immmo_item_liveness
from app.sources.base import PropertySource, RawProperty, SourceFetchError


async def _annotate_visibility_with_cursor(
    session: Session,
    source: Source,
    items: list[RawProperty],
    cursor: dict,
) -> dict:
    liveness = await prepare_immmo_item_liveness(session, source, items)
    counts = annotate_property_items_by_budget(items)
    next_cursor = dict(cursor)
    next_cursor["product_visible"] = sum(
        (item.raw_payload or {}).get("product_visible") is True for item in items
    )
    next_cursor["product_price_accepted"] = counts["accepted"]
    next_cursor["product_price_unknown"] = counts["price_unknown"]
    next_cursor["product_price_below_min"] = counts["price_below_min"]
    next_cursor["product_price_above_max"] = counts["price_above_max"]
    if source.name == "immmo.at":
        next_cursor["source_liveness_attempted"] = liveness.attempted
        next_cursor["source_liveness_live"] = liveness.live
        next_cursor["source_liveness_dead"] = liveness.dead
        next_cursor["source_liveness_unknown"] = liveness.unknown
    return next_cursor


async def run_property_source(
    session: Session,
    *,
    source: Source,
    adapter: PropertySource,
    reconciliation: bool = False,
) -> tuple[CrawlRun, CoverageSummary]:
    """Run all enabled shards sequentially and account for incomplete coverage.

    All parsed property observations are persisted for lifecycle and continuity. Father-facing
    visibility is stored as source-observation metadata and must not shrink `seen` coverage.
    IMMMO additionally verifies genuinely new downstream URLs before exposing them as product
    listings; synthetic fallback identities remain crawler-only.
    """
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
            next_cursor = await _annotate_visibility_with_cursor(
                session,
                source,
                batch.items,
                batch.next_cursor,
            )
            new_count, updated_count = ingest_properties(
                session,
                source=source,
                run=run,
                items=batch.items,
            )

            coverage_complete = batch.coverage_complete
            if source.name == "immmo.at":
                synthetic_new = synthetic_new_in_shard(
                    session,
                    source=source,
                    run=run,
                    items=batch.items,
                )
                decision = decide_immmo_coverage(
                    batch,
                    reconciliation=reconciliation,
                    synthetic_new=synthetic_new,
                )
                coverage_complete = decision.coverage_complete
                next_cursor = annotate_immmo_coverage_cursor(
                    next_cursor,
                    decision,
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
            shard_run.coverage_complete = coverage_complete
            shard_run.next_cursor = next_cursor

            shard.cursor = next_cursor
            shard.last_item_count = len(batch.items)
            shard.last_success_at = now
            shard.consecutive_failures = 0
            if reconciliation and coverage_complete and not batch.result_cap_hit:
                shard.last_full_scan_at = now
        except Exception as exc:
            # A failed flush/commit leaves SQLAlchemy in a failed transaction state. Roll it
            # back before touching ORM attributes. Source adapters may still provide all
            # successfully materialized items from pages completed before the failure; persist
            # those as non-authoritative discovery while keeping the shard itself FAILED.
            session.rollback()
            partial_new = 0
            partial_updated = 0
            partial_seen = 0
            partial_cursor = exc.next_cursor if isinstance(exc, SourceFetchError) else {}
            if isinstance(exc, SourceFetchError) and exc.partial_items:
                partial_source = session.get(Source, source_id)
                partial_run = session.get(CrawlRun, run_id)
                if partial_source is None or partial_run is None:
                    raise RuntimeError(
                        f"Could not reload partial-run state for {source.name}/{spec.key}"
                    ) from exc
                partial_items = cast(list[RawProperty], exc.partial_items)
                partial_cursor = await _annotate_visibility_with_cursor(
                    session,
                    partial_source,
                    partial_items,
                    exc.next_cursor,
                )
                partial_seen = len(partial_items)
                partial_new, partial_updated = ingest_properties(
                    session,
                    source=partial_source,
                    run=partial_run,
                    items=partial_items,
                )

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
                failed_shard_run.items_seen = partial_seen
                failed_shard_run.items_new = partial_new
                failed_shard_run.items_updated = partial_updated
                failed_shard_run.source_reported_count = exc.source_reported_count
                failed_shard_run.next_cursor = partial_cursor
            failed_shard.consecutive_failures += 1

        session.commit()

    summary = finalize_run(session, run)
    if reconciliation:
        # Full-coverage meta-search scans are the only safe moment to compact IMMMO
        # downstream-provider URL rotations. Do this before absence reconciliation so a
        # rotated URL refreshes the existing lifecycle row instead of looking disappeared.
        reconcile_immmo_continuity(session, run)
        reconcile_missing_listings(session, run)
    return run, summary
