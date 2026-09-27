from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, func, or_, select, update
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

SHARD_STATUS_SKIPPED = "skipped"
RUN_STATUS_PAUSED = "paused"


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
    shards_skipped: int
    shards_paused: int
    pages_fetched: int
    items_seen: int
    items_new: int
    items_updated: int
    source_reported_count: int | None


def summarize_shards(outcomes: list[ShardOutcome]) -> CoverageSummary:
    """Summarize execution health and source coverage as independent dimensions.

    A deliberately bounded incremental/frontier scan can execute perfectly while not
    claiming complete source coverage. In that case the run is SUCCESS and coverage is
    DEGRADED. Untouched shards after a source-wide halt are SKIPPED, not failures. A
    challenge-paused run is explicitly PAUSED and can never claim authoritative coverage.
    """
    total = len(outcomes)
    completed = sum(outcome.status == RunStatus.SUCCESS for outcome in outcomes)
    failed = sum(outcome.status == RunStatus.FAILED for outcome in outcomes)
    skipped = sum(outcome.status == SHARD_STATUS_SKIPPED for outcome in outcomes)
    paused = sum(outcome.status == RUN_STATUS_PAUSED for outcome in outcomes)
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
            shards_skipped=0,
            shards_paused=0,
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

    if paused:
        run_status = RUN_STATUS_PAUSED
        coverage_status = CoverageStatus.DEGRADED
    elif all_success:
        run_status = RunStatus.SUCCESS
        coverage_status = CoverageStatus.OK if complete else CoverageStatus.DEGRADED
    elif failed and completed == 0:
        run_status = RunStatus.FAILED
        coverage_status = CoverageStatus.FAILED
    else:
        run_status = RunStatus.PARTIAL
        coverage_status = CoverageStatus.DEGRADED

    return CoverageSummary(
        run_status=run_status,
        coverage_status=coverage_status,
        shards_total=total,
        shards_completed=completed,
        shards_failed=failed,
        shards_skipped=skipped,
        shards_paused=paused,
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


def summarize_run_state(session: Session, run: CrawlRun) -> CoverageSummary:
    shard_runs = list(
        session.scalars(
            select(CrawlShardRun)
            .where(CrawlShardRun.crawl_run_id == run.id)
            .order_by(CrawlShardRun.id)
        )
    )
    return summarize_shards(
        [
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
    )


def _write_summary(run: CrawlRun, summary: CoverageSummary) -> None:
    run.status = summary.run_status
    run.coverage_status = summary.coverage_status
    run.shards_total = summary.shards_total
    run.shards_completed = summary.shards_completed
    run.shards_failed = summary.shards_failed
    run.pages_fetched = summary.pages_fetched
    run.items_seen = summary.items_seen
    run.items_new = summary.items_new
    run.items_updated = summary.items_updated
    run.source_reported_count = summary.source_reported_count
    metadata = dict(run.run_metadata or {})
    metadata["telemetry"] = {
        "shards_completed": summary.shards_completed,
        "shards_failed": summary.shards_failed,
        "shards_skipped": summary.shards_skipped,
        "shards_paused": summary.shards_paused,
    }
    run.run_metadata = metadata


def checkpoint_paused_run(session: Session, run: CrawlRun) -> CoverageSummary:
    """Persist aggregate counters for a resumable run without finishing it."""
    summary = summarize_run_state(session, run)
    _write_summary(run, summary)
    run.status = RUN_STATUS_PAUSED
    run.coverage_status = CoverageStatus.DEGRADED
    run.finished_at = None
    session.commit()
    return summary


def finalize_run(session: Session, run: CrawlRun) -> CoverageSummary:
    summary = summarize_run_state(session, run)
    now = datetime.now(UTC)

    _write_summary(run, summary)
    run.finished_at = now

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


def _previous_ok_reconciliation(
    session: Session,
    run: CrawlRun,
    *,
    offset: int = 0,
) -> CrawlRun | None:
    return session.scalar(
        select(CrawlRun)
        .where(
            CrawlRun.source_id == run.source_id,
            CrawlRun.id != run.id,
            CrawlRun.mode == CrawlMode.RECONCILIATION,
            CrawlRun.coverage_status == CoverageStatus.OK,
            CrawlRun.started_at < run.started_at,
        )
        .order_by(CrawlRun.started_at.desc())
        .offset(offset)
        .limit(1)
    )


def _stable_property_identity() -> tuple:
    """Select rows whose source identity is safe for the normal two-scan absence rule."""
    identity_stable = func.coalesce(
        PropertyListing.raw_payload.op("->>")("identity_stable"),
        "true",
    )
    original_url_missing = func.coalesce(
        PropertyListing.raw_payload.op("->>")("original_url_missing"),
        "false",
    )
    return identity_stable != "false", original_url_missing != "true"


def _synthetic_property_identity():
    """Select IMMMO-style synthetic identities that need a longer absence window."""
    identity_stable = func.coalesce(
        PropertyListing.raw_payload.op("->>")("identity_stable"),
        "true",
    )
    original_url_missing = func.coalesce(
        PropertyListing.raw_payload.op("->>")("original_url_missing"),
        "false",
    )
    return or_(identity_stable == "false", original_url_missing == "true")


def reconcile_missing_listings(session: Session, run: CrawlRun) -> tuple[int, int]:
    """Deactivate only listings confirmed absent across complete scans.

    Live offset-paginated sources can move records between pages while a full scan is
    running. Stable source identities therefore require absence from two consecutive
    complete scans. Synthetic IMMMO fallback identities are intentionally more cautious:
    because their fingerprint contains mutable card metadata, they require absence from
    three consecutive complete scans before deactivation.

    Degraded/partial/failed reconciliations never count. Any incremental sighting between
    full scans refreshes ``last_seen_at`` and therefore resets the effective absence window.
    """
    if run.mode != CrawlMode.RECONCILIATION or run.coverage_status != CoverageStatus.OK:
        return 0, 0

    previous = _previous_ok_reconciliation(session, run)
    if previous is None:
        run.items_disappeared = 0
        session.commit()
        return 0, 0

    now = datetime.now(UTC)

    stable_result = session.execute(
        update(PropertyListing)
        .where(
            PropertyListing.source_id == run.source_id,
            PropertyListing.status == ListingStatus.ACTIVE,
            PropertyListing.last_seen_crawl_run_id.is_distinct_from(run.id),
            PropertyListing.last_seen_at < previous.started_at,
            *_stable_property_identity(),
        )
        .values(status=ListingStatus.INACTIVE, inactive_at=now)
    )

    synthetic_count = 0
    second_previous = _previous_ok_reconciliation(session, run, offset=1)
    if second_previous is not None:
        synthetic_result = session.execute(
            update(PropertyListing)
            .where(
                PropertyListing.source_id == run.source_id,
                PropertyListing.status == ListingStatus.ACTIVE,
                PropertyListing.last_seen_crawl_run_id.is_distinct_from(run.id),
                PropertyListing.last_seen_at < second_previous.started_at,
                _synthetic_property_identity(),
            )
            .values(status=ListingStatus.INACTIVE, inactive_at=now)
        )
        synthetic_count = synthetic_result.rowcount or 0

    job_result = session.execute(
        update(JobListing)
        .where(
            JobListing.source_id == run.source_id,
            JobListing.status == ListingStatus.ACTIVE,
            JobListing.last_seen_crawl_run_id.is_distinct_from(run.id),
            JobListing.last_seen_at < previous.started_at,
        )
        .values(status=ListingStatus.INACTIVE, inactive_at=now)
    )
    property_count = (stable_result.rowcount or 0) + synthetic_count
    job_count = job_result.rowcount or 0

    _sync_canonical_lifecycle(session, now=now)

    run.items_disappeared = property_count + job_count
    session.commit()
    return property_count, job_count
