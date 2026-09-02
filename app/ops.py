from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin import AdminDependency, DbDependency
from app.jobs.location_resolution import is_non_point_location_scope
from app.models import (
    CoverageStatus,
    CrawlRun,
    CrawlShardRun,
    Job,
    JobListing,
    JobLocation,
    ListingStatus,
    Property,
    RunStatus,
    Source,
    SourceCategory,
    SourceShard,
)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@dataclass(frozen=True, slots=True)
class SourceOpsRow:
    name: str
    category: str
    enabled: bool
    state: str
    coverage_status: str
    poll_interval_minutes: int
    last_success_at: datetime | None
    latest_run_id: int | None
    latest_mode: str | None
    latest_status: str | None
    latest_started_at: datetime | None
    latest_items_seen: int | None
    latest_shards_failed: int | None
    failing_shards: int
    last_error: str | None


@dataclass(frozen=True, slots=True)
class JobSourceValueRow:
    name: str
    enabled: bool
    active_accepted_listings: int
    catalog_jobs: int
    exclusive_jobs: int
    shared_jobs: int
    latest_candidates: int | None
    latest_accepted: int | None
    latest_rejected: int | None

    @property
    def latest_yield_percent(self) -> float | None:
        if self.latest_candidates is None:
            return None
        if self.latest_candidates <= 0:
            return 0.0
        if self.latest_accepted is None:
            return None
        return self.latest_accepted * 100.0 / self.latest_candidates


@dataclass(frozen=True, slots=True)
class OpsSnapshot:
    active_properties: int
    active_jobs: int
    unresolved_job_locations: int
    enabled_sources: int
    sources: tuple[SourceOpsRow, ...]
    unresolved_labels: tuple[tuple[str, int], ...]
    visible_jobs: int = 0
    job_sources: tuple[JobSourceValueRow, ...] = ()
    non_point_job_locations: int = 0
    non_point_labels: tuple[tuple[str, int], ...] = ()


def _age_minutes(value: datetime | None, now: datetime) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return max(0.0, (now - value.astimezone(UTC)).total_seconds() / 60.0)


def source_ops_state(
    source: Source,
    latest: CrawlRun | None,
    failing_shards: int,
    *,
    now: datetime,
) -> str:
    if not source.enabled:
        return "deaktiviert"
    if source.coverage_status in {CoverageStatus.DEGRADED, CoverageStatus.FAILED}:
        return "warnung"
    if latest is not None and latest.status == RunStatus.FAILED:
        return "warnung"
    if latest is not None and latest.status == RunStatus.PARTIAL:
        # Before v0.3.11, a deliberately bounded scan was recorded as PARTIAL even when
        # every shard executed successfully. Treat that legacy state as healthy when
        # there is no execution failure; new runs already record this as SUCCESS/DEGRADED.
        shards_failed = int(getattr(latest, "shards_failed", 0) or 0)
        shards_total = int(getattr(latest, "shards_total", 0) or 0)
        shards_completed = int(getattr(latest, "shards_completed", 0) or 0)
        if shards_failed or (shards_total and shards_completed < shards_total):
            return "warnung"
    if failing_shards:
        return "warnung"
    age = _age_minutes(source.last_success_at, now)
    if age is None:
        return "ohne_erfolg"
    stale_after = max(180, source.poll_interval_minutes * 3)
    if age > stale_after:
        return "veraltet"
    return "ok"


def split_unresolved_location_labels(
    rows: Iterable[tuple[str, int]],
) -> tuple[tuple[tuple[str, int], ...], tuple[tuple[str, int], ...]]:
    """Separate genuine point-resolution backlog from intentional non-point scopes."""
    concrete: list[tuple[str, int]] = []
    non_point: list[tuple[str, int]] = []
    for label, count in rows:
        item = (str(label), int(count))
        if is_non_point_location_scope(label):
            non_point.append(item)
        else:
            concrete.append(item)
    return tuple(concrete), tuple(non_point)


def _gate_accepted(raw_payload: dict | None) -> bool:
    gate = (raw_payload or {}).get("wohnwerk_discovery_gate")
    return isinstance(gate, dict) and gate.get("accepted") is True


def _job_source_contributions(
    db: Session,
    sources: list[Source],
) -> tuple[int, dict[int, tuple[int, int, int, int]]]:
    enabled_job_source_ids = {
        source.id
        for source in sources
        if source.enabled and source.category == SourceCategory.JOB
    }
    if not enabled_job_source_ids:
        return 0, {}

    accepted_listing_counts: Counter[int] = Counter()
    contributors_by_job: dict[int, set[int]] = defaultdict(set)
    rows = db.execute(
        select(JobListing.job_id, JobListing.source_id, JobListing.raw_payload)
        .join(Job, Job.id == JobListing.job_id)
        .where(
            Job.status == ListingStatus.ACTIVE,
            JobListing.status == ListingStatus.ACTIVE,
            JobListing.source_id.in_(enabled_job_source_ids),
        )
    )
    for job_id, source_id, raw_payload in rows:
        if not _gate_accepted(raw_payload):
            continue
        accepted_listing_counts[int(source_id)] += 1
        contributors_by_job[int(job_id)].add(int(source_id))

    catalog_counts: Counter[int] = Counter()
    exclusive_counts: Counter[int] = Counter()
    shared_counts: Counter[int] = Counter()
    for source_ids in contributors_by_job.values():
        for source_id in source_ids:
            catalog_counts[source_id] += 1
            if len(source_ids) == 1:
                exclusive_counts[source_id] += 1
            else:
                shared_counts[source_id] += 1

    contributions = {
        source.id: (
            accepted_listing_counts[source.id],
            catalog_counts[source.id],
            exclusive_counts[source.id],
            shared_counts[source.id],
        )
        for source in sources
        if source.category == SourceCategory.JOB
    }
    return len(contributors_by_job), contributions


def _latest_candidate_totals(
    shard_rows: list[CrawlShardRun],
) -> tuple[int | None, int | None, int | None]:
    totals = [0, 0, 0]
    found = False
    keys = (
        "job_candidates_fetched",
        "job_candidates_accepted",
        "job_candidates_rejected",
    )
    for row in shard_rows:
        cursor = row.next_cursor or {}
        for index, key in enumerate(keys):
            value = cursor.get(key)
            if isinstance(value, int):
                totals[index] += value
                found = True
    if not found:
        return None, None, None
    return totals[0], totals[1], totals[2]


def collect_ops_snapshot(db: Session, *, now: datetime | None = None) -> OpsSnapshot:
    now = (now or datetime.now(UTC)).astimezone(UTC)

    active_properties = int(
        db.scalar(
            select(func.count()).select_from(Property).where(
                Property.status == ListingStatus.ACTIVE
            )
        )
        or 0
    )
    active_jobs = int(
        db.scalar(
            select(func.count()).select_from(Job).where(Job.status == ListingStatus.ACTIVE)
        )
        or 0
    )

    raw_unresolved_labels = tuple(
        (str(city), int(count))
        for city, count in db.execute(
            select(JobLocation.city, func.count())
            .join(Job, Job.id == JobLocation.job_id)
            .where(
                Job.status == ListingStatus.ACTIVE,
                JobLocation.remote.is_(False),
                JobLocation.city.is_not(None),
                JobLocation.location.is_(None),
            )
            .group_by(JobLocation.city)
            .order_by(func.count().desc(), JobLocation.city)
        )
    )
    unresolved_labels, non_point_labels = split_unresolved_location_labels(
        raw_unresolved_labels
    )
    unresolved_job_locations = sum(count for _label, count in unresolved_labels)
    non_point_job_locations = sum(count for _label, count in non_point_labels)

    sources = list(db.scalars(select(Source).order_by(Source.category, Source.name)))
    visible_jobs, contribution_by_source = _job_source_contributions(db, sources)
    rows: list[SourceOpsRow] = []
    value_rows: list[JobSourceValueRow] = []

    for source in sources:
        latest = db.scalar(
            select(CrawlRun)
            .where(CrawlRun.source_id == source.id)
            .order_by(CrawlRun.started_at.desc(), CrawlRun.id.desc())
            .limit(1)
        )
        failing_shards = int(
            db.scalar(
                select(func.count())
                .select_from(SourceShard)
                .where(
                    SourceShard.source_id == source.id,
                    SourceShard.enabled.is_(True),
                    SourceShard.consecutive_failures > 0,
                )
            )
            or 0
        )
        rows.append(
            SourceOpsRow(
                name=source.name,
                category=source.category,
                enabled=source.enabled,
                state=source_ops_state(source, latest, failing_shards, now=now),
                coverage_status=source.coverage_status,
                poll_interval_minutes=source.poll_interval_minutes,
                last_success_at=source.last_success_at,
                latest_run_id=latest.id if latest else None,
                latest_mode=latest.mode if latest else None,
                latest_status=latest.status if latest else None,
                latest_started_at=latest.started_at if latest else None,
                latest_items_seen=latest.items_seen if latest else None,
                latest_shards_failed=latest.shards_failed if latest else None,
                failing_shards=failing_shards,
                last_error=source.last_error,
            )
        )

        if source.category == SourceCategory.JOB:
            latest_shards = (
                list(
                    db.scalars(
                        select(CrawlShardRun)
                        .where(CrawlShardRun.crawl_run_id == latest.id)
                        .order_by(CrawlShardRun.id)
                    )
                )
                if latest is not None
                else []
            )
            candidates, accepted, rejected = _latest_candidate_totals(latest_shards)
            active_listings, catalog_jobs, exclusive_jobs, shared_jobs = (
                contribution_by_source.get(source.id, (0, 0, 0, 0))
            )
            value_rows.append(
                JobSourceValueRow(
                    name=source.name,
                    enabled=source.enabled,
                    active_accepted_listings=active_listings,
                    catalog_jobs=catalog_jobs,
                    exclusive_jobs=exclusive_jobs,
                    shared_jobs=shared_jobs,
                    latest_candidates=candidates,
                    latest_accepted=accepted,
                    latest_rejected=rejected,
                )
            )

    value_rows.sort(
        key=lambda row: (
            not row.enabled,
            -row.exclusive_jobs,
            -row.catalog_jobs,
            row.name,
        )
    )

    return OpsSnapshot(
        active_properties=active_properties,
        active_jobs=active_jobs,
        unresolved_job_locations=unresolved_job_locations,
        enabled_sources=sum(source.enabled for source in sources),
        sources=tuple(rows),
        unresolved_labels=unresolved_labels[:20],
        visible_jobs=visible_jobs,
        job_sources=tuple(value_rows),
        non_point_job_locations=non_point_job_locations,
        non_point_labels=non_point_labels[:20],
    )


@router.get("/health")
def admin_health_page(
    request: Request,
    _: AdminDependency,
    db: DbDependency,
):
    return templates.TemplateResponse(
        request=request,
        name="admin_health.html",
        context={
            "snapshot": collect_ops_snapshot(db),
        },
    )
