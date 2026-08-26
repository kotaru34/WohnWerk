from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app.models import (
    CoverageStatus,
    CrawlMode,
    CrawlRun,
    CrawlShardRun,
    Job,
    JobListing,
    ListingStatus,
    Property,
    PropertyListing,
    RunStatus,
    Source,
    SourceShard,
)


@dataclass(frozen=True, slots=True)
class ShardOutcome:
    status: str
    pages_fetched: int = 0
    items_seen: int = 0
    items_new: int = 0
    items_updated: int = 0
    source_reported_count: int | None = None
    result_cap_hit: bool = False
    coverage_complete: bool = False


@dataclass(frozen=True, slots=True)
class CoverageSummary:
    run_status: str
    coverage_status: str
    shards_total: int
    shards_completed: int
    shards_failed: int
    pages_fetched: int
    items_seen: int
    items_new: int
    items_updated: int
    source_reported_count: int | None


def summarize_shards(outcomes: list[ShardOutcome]) -> CoverageSummary:
    """Summarize shard outcomes without pretending a partial scan is complete."""
    total = len(outcomes)
    completed = sum(outcome.status == RunStatus.SUCCESS for outcome in outcomes)
    failed = sum(outcome.status == RunStatus.FAILED for outcome in outcomes)
    pages = sum(outcome.pages_fetched for outcome in outcomes)
    seen = sum(outcome.items_seen for outcome in outcomes)
    new = sum(outcome.items_new for outcome in outcomes)
    updated = sum(outcome.items_updated for outcome in outcomes)

    reported_counts = [
        outcome.source_reported_count
        for outcome in outcomes
        if outcome.source_reported_count is not None
    ]
    source_reported_count = sum(reported_counts) if reported_counts else None

    if total == 0:
        return CoverageSummary(
            run_status=RunStatus.FAILED,
            coverage_status=CoverageStatus.FAILED,
            shards_total=0,
            shards_completed=0,
            shards_failed=0,
            pages_fetched=0,
            items_seen=0,
            items_new=0,
            items_updated=0,
            source_reported_count=None,
        )

    all_success = completed == total
    complete = all(
        outcome.status == RunStatus.SUCCESS
        and outcome.coverage_complete
        and not outcome.result_cap_hit
        for outcome in outcomes
    )

    if complete:
        run_status = RunStatus.SUCCESS
        coverage_status = CoverageStatus.OK
    elif failed == total:
        run_status = RunStatus.FAILED
        coverage_status = CoverageStatus.FAILED
    else:
        run_status = RunStatus.PARTIAL if not all_success or not complete else RunStatus.SUCCESS
        coverage_status = CoverageStatus.DEGRADED

    return CoverageSummary(
        run_status=run_status,
        coverage_status=coverage_status,
        shards_total=total,
        shards_completed=completed,
        shards_failed=failed,
        pages_fetched=pages,
        items_seen=seen,
        items_new=new,
        items_updated=updated,
        source_reported_count=source_reported_count,
    )


def create_run(session: Session, source: Source, mode: CrawlMode) -> CrawlRun:
    shards = list(
        session.scalars(
            select(SourceShard)
            .where(SourceShard.source_id == source.id, SourceShard.enabled.is_(True))
            .order_by(SourceShard.priority, SourceShard.id)
        )
    )
    run = CrawlRun(source_id=source.id, mode=mode, shards_total=len(shards))
    session.add(run)
    session.flush()

    for shard in shards:
        session.add(CrawlShardRun(crawl_run_id=run.id, shard_id=shard.id))

    session.commit()
    return run


def finalize_run(session: Session, run: CrawlRun) -> CoverageSummary:
    shard_runs = list(
        session.scalars(
            select(CrawlShardRun)
            .where(CrawlShardRun.crawl_run_id == run.id)
            .order_by(CrawlShardRun.id)
        )
    )
    outcomes = [
        ShardOutcome(
            status=shard.status,
            pages_fetched=shard.pages_fetched,
            items_seen=shard.items_seen,
            items_new=shard.items_new,
            items_updated=shard.items_updated,
            source_reported_count=shard.source_reported_count,
            result_cap_hit=shard.result_cap_hit,
            coverage_complete=shard.coverage_complete,
        )
        for shard in shard_runs
    ]
    summary = summarize_shards(outcomes)
    now = datetime.now(UTC)

    run.status = summary.run_status
    run.coverage_status = summary.coverage_status
    run.finished_at = now
    run.shards_total = summary.shards_total
    run.shards_completed = summary.shards_completed
    run.shards_failed = summary.shards_failed
    run.pages_fetched = summary.pages_fetched
    run.items_seen = summary.items_seen
    run.items_new = summary.items_new
    run.items_updated = summary.items_updated
    run.source_reported_count = summary.source_reported_count

    source = session.get(Source, run.source_id)
    if source is not None:
        if run.mode == CrawlMode.INCREMENTAL:
            source.last_incremental_at = now
        elif run.mode == CrawlMode.RECONCILIATION:
            source.coverage_status = summary.coverage_status
            if summary.coverage_status == CoverageStatus.OK:
                source.last_reconciliation_at = now
        if summary.run_status == RunStatus.SUCCESS:
            source.last_success_at = now

    session.commit()
    return summary


def _sync_canonical_lifecycle(session: Session, *, now: datetime) -> None:
    """Deactivate canonical rows only when none of their source listings is active."""
    active_property_listing = exists(
        select(PropertyListing.id).where(
            PropertyListing.property_id == Property.id,
            PropertyListing.status == ListingStatus.ACTIVE,
        )
    )
    session.execute(
        update(Property)
        .where(
            Property.status == ListingStatus.ACTIVE,
            ~active_property_listing,
        )
        .values(status=ListingStatus.INACTIVE, inactive_at=now)
    )

    active_job_listing = exists(
        select(JobListing.id).where(
            JobListing.job_id == Job.id,
            JobListing.status == ListingStatus.ACTIVE,
        )
    )
    session.execute(
        update(Job)
        .where(
            Job.status == ListingStatus.ACTIVE,
            ~active_job_listing,
        )
        .values(status=ListingStatus.INACTIVE, inactive_at=now)
    )


def reconcile_missing_listings(session: Session, run: CrawlRun) -> tuple[int, int]:
    """Deactivate unseen source listings only after a complete reconciliation cycle."""
    if run.mode != CrawlMode.RECONCILIATION or run.coverage_status != CoverageStatus.OK:
        return 0, 0

    now = datetime.now(UTC)
    property_result = session.execute(
        update(PropertyListing)
        .where(
            PropertyListing.source_id == run.source_id,
            PropertyListing.status == ListingStatus.ACTIVE,
            PropertyListing.last_seen_crawl_run_id.is_distinct_from(run.id),
        )
        .values(status=ListingStatus.INACTIVE, inactive_at=now)
    )
    job_result = session.execute(
        update(JobListing)
        .where(
            JobListing.source_id == run.source_id,
            JobListing.status == ListingStatus.ACTIVE,
            JobListing.last_seen_crawl_run_id.is_distinct_from(run.id),
        )
        .values(status=ListingStatus.INACTIVE, inactive_at=now)
    )
    property_count = property_result.rowcount or 0
    job_count = job_result.rowcount or 0

    _sync_canonical_lifecycle(session, now=now)

    run.items_disappeared = property_count + job_count
    session.commit()
    return property_count, job_count
