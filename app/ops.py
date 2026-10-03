from __future__ import annotations

import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin import AdminDependency, CsrfDependency, DbDependency, _csrf_token
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
from app.refresh import source_is_scheduled, source_operational_note, source_run_plan

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
PROJECT_ROOT = Path(__file__).resolve().parents[1]

NOTICE_LABELS = {
    "source_enabled": "Quelle aktiviert.",
    "source_disabled": "Quelle deaktiviert.",
    "run_started": "Manueller Quellenlauf wurde gestartet.",
    "already_running": "Für diese Quelle läuft bereits ein Crawl.",
}


@dataclass(frozen=True, slots=True)
class SourceOpsRow:
    id: int
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
    state_reason: str
    latest_error: str | None
    latest_pages_fetched: int | None
    latest_items_new: int | None
    latest_items_updated: int | None
    latest_items_disappeared: int | None
    latest_shards_total: int | None
    latest_shards_completed: int | None
    shard_errors: tuple[str, ...]
    scheduled: bool
    runnable: bool
    operational_note: str | None


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
    scheduled: bool = True,
    runnable: bool = True,
) -> str:
    if not source.enabled:
        return "deaktiviert"
    if latest is not None and latest.status == RunStatus.RUNNING:
        return "läuft"
    if runnable and not scheduled:
        return "warnung"
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


def source_ops_reason(
    source: Source,
    latest: CrawlRun | None,
    failing_shards: int,
    shard_errors: tuple[str, ...],
    *,
    now: datetime,
    scheduled: bool = True,
    runnable: bool = True,
    operational_note: str | None = None,
) -> str:
    if not source.enabled:
        return "Vom Administrator deaktiviert; automatische und manuelle Läufe sind gesperrt."

    if latest is not None and latest.status == RunStatus.RUNNING:
        return f"Lauf #{latest.id} läuft seit {latest.started_at:%d.%m.%Y %H:%M}."

    latest_error = (latest.error if latest is not None else None) or source.last_error
    if latest is not None and latest.status == RunStatus.FAILED:
        detail = latest_error or "kein Fehlertext gespeichert"
        return f"Lauf #{latest.id} fehlgeschlagen: {detail}"

    if latest is not None and latest.status == RunStatus.PARTIAL:
        failed = int(getattr(latest, "shards_failed", 0) or 0)
        total = int(getattr(latest, "shards_total", 0) or 0)
        completed = int(getattr(latest, "shards_completed", 0) or 0)
        if failed or (total and completed < total):
            detail = shard_errors[0] if shard_errors else latest_error
            suffix = f" Ursache: {detail}" if detail else ""
            return (
                f"Lauf #{latest.id} nur teilweise: {completed}/{total} Shards abgeschlossen, "
                f"{failed} fehlgeschlagen.{suffix}"
            )

    if source.coverage_status in {CoverageStatus.DEGRADED, CoverageStatus.FAILED}:
        detail = latest_error or (shard_errors[0] if shard_errors else None)
        suffix = f": {detail}" if detail else ""
        return f"Coverage ist {source.coverage_status}{suffix}"

    if failing_shards:
        suffix = f" Letzter Shard-Fehler: {shard_errors[0]}" if shard_errors else ""
        return f"{failing_shards} aktive Shards haben aufeinanderfolgende Fehler.{suffix}"

    if runnable and not scheduled:
        return operational_note or "Quelle ist nur für manuelle Diagnose-Läufe registriert."

    age = _age_minutes(source.last_success_at, now)
    if age is None:
        return operational_note or "Noch kein erfolgreicher Lauf gespeichert."

    stale_after = max(180, source.poll_interval_minutes * 3)
    if age > stale_after:
        return (
            f"Letzter Erfolg vor {age / 60:.1f} h; erwartet wird spätestens nach "
            f"{stale_after / 60:.1f} h ein erfolgreicher Lauf."
        )

    return operational_note or "Letzter Lauf und Coverage sind ohne aktuellen Fehler."


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
        latest_shard_errors = (
            tuple(
                str(error)
                for error in db.scalars(
                    select(CrawlShardRun.error)
                    .where(
                        CrawlShardRun.crawl_run_id == latest.id,
                        CrawlShardRun.error.is_not(None),
                    )
                    .order_by(CrawlShardRun.id)
                    .limit(3)
                )
                if error
            )
            if latest is not None
            else ()
        )
        plan = source_run_plan(source.name)
        scheduled = source_is_scheduled(source.name)
        runnable = plan is not None
        operational_note = source_operational_note(source.name)
        state = source_ops_state(
            source,
            latest,
            failing_shards,
            now=now,
            scheduled=scheduled,
            runnable=runnable,
        )
        rows.append(
            SourceOpsRow(
                id=source.id,
                name=source.name,
                category=source.category,
                enabled=source.enabled,
                state=state,
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
                state_reason=source_ops_reason(
                    source,
                    latest,
                    failing_shards,
                    latest_shard_errors,
                    now=now,
                    scheduled=scheduled,
                    runnable=runnable,
                    operational_note=operational_note,
                ),
                latest_error=latest.error if latest else None,
                latest_pages_fetched=latest.pages_fetched if latest else None,
                latest_items_new=latest.items_new if latest else None,
                latest_items_updated=latest.items_updated if latest else None,
                latest_items_disappeared=latest.items_disappeared if latest else None,
                latest_shards_total=latest.shards_total if latest else None,
                latest_shards_completed=latest.shards_completed if latest else None,
                shard_errors=latest_shard_errors,
                scheduled=scheduled,
                runnable=runnable,
                operational_note=operational_note,
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


def _health_redirect(notice: str) -> RedirectResponse:
    return RedirectResponse(f"/admin/health?{urlencode({'hinweis': notice})}", status_code=303)


@router.post("/sources/{source_id}/enabled")
def set_source_enabled(
    source_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    enabled: str = Form(),
):
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Quelle nicht gefunden.")
    source.enabled = enabled == "1"
    db.commit()
    return _health_redirect("source_enabled" if source.enabled else "source_disabled")


@router.post("/sources/{source_id}/run")
def run_source_now(
    source_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
):
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Quelle nicht gefunden.")
    if not source.enabled:
        raise HTTPException(status_code=409, detail="Deaktivierte Quelle kann nicht gestartet werden.")
    if source_run_plan(source.name) is None:
        raise HTTPException(status_code=409, detail="Quelle ist nicht für manuelle Läufe registriert.")

    running = db.scalar(
        select(CrawlRun.id)
        .where(
            CrawlRun.source_id == source.id,
            CrawlRun.status == RunStatus.RUNNING,
            CrawlRun.finished_at.is_(None),
        )
        .order_by(CrawlRun.id.desc())
        .limit(1)
    )
    if running is not None:
        return _health_redirect("already_running")

    try:
        subprocess.Popen(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "refresh_sources.py"),
                "--source",
                source.name,
            ],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Quellenlauf konnte nicht gestartet werden: {exc}",
        ) from exc
    return _health_redirect("run_started")


@router.get("/health")
def admin_health_page(
    request: Request,
    _: AdminDependency,
    db: DbDependency,
    hinweis: str | None = None,
):
    return templates.TemplateResponse(
        request=request,
        name="admin_health.html",
        context={
            "snapshot": collect_ops_snapshot(db),
            "csrf_token": _csrf_token(),
            "notice": NOTICE_LABELS.get(hinweis or ""),
        },
    )
