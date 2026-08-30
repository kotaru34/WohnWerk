from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin import AdminDependency, DbDependency
from app.models import (
    CoverageStatus,
    CrawlRun,
    Job,
    JobLocation,
    ListingStatus,
    Property,
    RunStatus,
    Source,
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
class OpsSnapshot:
    active_properties: int
    active_jobs: int
    unresolved_job_locations: int
    enabled_sources: int
    sources: tuple[SourceOpsRow, ...]
    unresolved_labels: tuple[tuple[str, int], ...]


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
    if latest is not None and latest.status in {RunStatus.PARTIAL, RunStatus.FAILED}:
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
    unresolved_job_locations = int(
        db.scalar(
            select(func.count())
            .select_from(JobLocation)
            .join(Job, Job.id == JobLocation.job_id)
            .where(
                Job.status == ListingStatus.ACTIVE,
                JobLocation.remote.is_(False),
                JobLocation.city.is_not(None),
                JobLocation.location.is_(None),
            )
        )
        or 0
    )

    unresolved_labels = tuple(
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
            .limit(20)
        )
    )

    sources = list(db.scalars(select(Source).order_by(Source.category, Source.name)))
    rows: list[SourceOpsRow] = []
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

    return OpsSnapshot(
        active_properties=active_properties,
        active_jobs=active_jobs,
        unresolved_job_locations=unresolved_job_locations,
        enabled_sources=sum(source.enabled for source in sources),
        sources=tuple(rows),
        unresolved_labels=unresolved_labels,
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
