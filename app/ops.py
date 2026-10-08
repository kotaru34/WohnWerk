from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin import AdminDependency, CsrfDependency, DbDependency, _csrf_token
from app.crawling.immowelt_operator_handoff import (
    INTERACTIVE_DATADOME_TYPES,
    arm_operator_handoff,
    challenge_state_for_run,
    enqueue_operator_pointer,
    operator_frame_path,
    operator_run_dir,
    prepare_fresh_operator_reverification,
    read_operator_status,
)
from app.crawling.immowelt_operator_ready import (
    arm_operator_readiness,
    bind_operator_readiness,
    clear_operator_readiness,
    read_operator_readiness,
)
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
from app.refresh import (
    MANUAL_RUN_BUSY_EXIT_CODE,
    MANUAL_RUN_DEFERRED_EXIT_CODE,
    source_is_scheduled,
    source_operational_note,
    source_run_plan,
)
from app.refresh_runtime import REFRESH_LOCK_PATH

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
PROJECT_ROOT = Path(__file__).resolve().parents[1]

NOTICE_LABELS = {
    "source_enabled": "Quelle aktiviert.",
    "source_disabled": "Quelle deaktiviert.",
    "run_started": "Manueller Quellenlauf wurde gestartet.",
    "run_resumed": "Pausierter Quellenlauf wurde manuell fortgesetzt.",
    "already_running": "Für diese Quelle läuft bereits ein Crawl.",
    "refresh_busy": "Ein anderer Refresh läuft bereits; der manuelle Lauf wurde nicht gestartet.",
    "run_deferred": "Der manuelle Lauf wurde vom Runtime-Gate zurückgestellt und nicht gestartet.",
    "run_failed": "Der manuelle Quellenlauf konnte nicht gestartet werden.",
    "run_pending": "Der manuelle Start läuft, aber eine neue Lauf-ID ist noch nicht sichtbar.",
    "challenge_cancelled": "Interaktive Immowelt-Prüfung wurde abgebrochen; der Lauf bleibt pausiert.",
    "operator_ready": "Immowelt-Begleitung ist 15 Minuten bereit. Jetzt manuellen Lauf starten.",
    "operator_ready_cleared": "Immowelt-Begleitung wurde deaktiviert.",
}

RUN_START_CONFIRM_TIMEOUT_SECONDS = 3.0
RUN_START_POLL_SECONDS = 0.05


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
    latest_activity_at: datetime | None = None
    latest_resume_at: datetime | None = None
    interactive_challenge: bool = False
    interactive_challenge_type: str | None = None


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


def _metadata_datetime(value: object | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _run_resume_at(run: CrawlRun | None) -> datetime | None:
    if run is None:
        return None
    metadata = dict(getattr(run, "run_metadata", None) or {})
    values: list[datetime] = []
    manual = _metadata_datetime(metadata.get("manual_resume_requested_at"))
    if manual is not None:
        values.append(manual)
    history = metadata.get("challenge_history")
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict) or item.get("action") != "revalidate":
                continue
            value = _metadata_datetime(item.get("at"))
            if value is not None:
                values.append(value)
    return max(values) if values else None


def _run_activity_at(run: CrawlRun | None) -> datetime | None:
    if run is None:
        return None
    values: list[datetime] = []
    started = getattr(run, "started_at", None)
    if isinstance(started, datetime):
        values.append(
            started.replace(tzinfo=UTC)
            if started.tzinfo is None
            else started.astimezone(UTC)
        )

    metadata = dict(getattr(run, "run_metadata", None) or {})
    explicit_activity = _metadata_datetime(metadata.get("last_activity_at"))
    if explicit_activity is not None:
        values.append(explicit_activity)

    resume = _run_resume_at(run)
    if resume is not None:
        values.append(resume)

    history = metadata.get("challenge_history")
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            value = _metadata_datetime(item.get("at"))
            if value is not None:
                values.append(value)
    return max(values) if values else None


def _interactive_challenge_type(run: CrawlRun | None) -> str | None:
    if run is None or str(run.status) != "paused":
        return None
    active = dict(run.run_metadata or {}).get("active_challenge")
    if not isinstance(active, dict):
        return None
    challenge = active.get("challenge")
    if not isinstance(challenge, dict):
        return None
    value = str(challenge.get("datadome_challenge_type") or "").strip().casefold()
    return value if value in INTERACTIVE_DATADOME_TYPES else None


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
    if latest is not None and str(latest.status) == "paused":
        return "warnung"
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
    supports_reconciliation: bool = True,
) -> str:
    if not source.enabled:
        return "Vom Administrator deaktiviert; automatische und manuelle Läufe sind gesperrt."

    if latest is not None and latest.status == RunStatus.RUNNING:
        activity = _run_activity_at(latest)
        resume = _run_resume_at(latest)
        if activity is not None and activity > latest.started_at:
            suffix = " (fortgesetzter pausierter Lauf)" if resume is not None else ""
            return (
                f"Lauf #{latest.id} aktiv: Start {latest.started_at:%d.%m.%Y %H:%M}, "
                f"letzte Aktivität {activity:%d.%m.%Y %H:%M}{suffix}."
            )
        return f"Lauf #{latest.id} läuft seit {latest.started_at:%d.%m.%Y %H:%M}."

    if latest is not None and str(latest.status) == "paused":
        activity = _run_activity_at(latest)
        activity_text = (
            f", letzte Aktivität {activity:%d.%m.%Y %H:%M}"
            if activity is not None and activity > latest.started_at
            else ""
        )
        return (
            f"Lauf #{latest.id} pausiert: Start {latest.started_at:%d.%m.%Y %H:%M}"
            f"{activity_text}; wartet auf Challenge-Fortsetzung."
        )

    latest_error = (
        getattr(latest, "error", None) if latest is not None else None
    ) or getattr(source, "last_error", None)
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
        if (
            source.coverage_status == CoverageStatus.DEGRADED
            and not supports_reconciliation
            and latest is not None
            and latest.status == RunStatus.SUCCESS
        ):
            return (
                "Letzter Lauf erfolgreich; Coverage bleibt absichtlich degraded, weil "
                "diese Quelle nur einen begrenzten Frontier-Scan liefert und deshalb "
                "keine Vollständigkeit bzw. Disappearance-Authority behauptet."
            )
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
                    supports_reconciliation=(
                        plan.supports_reconciliation if plan is not None else False
                    ),
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
                latest_activity_at=_run_activity_at(latest),
                latest_resume_at=_run_resume_at(latest),
                interactive_challenge=_interactive_challenge_type(latest) is not None,
                interactive_challenge_type=_interactive_challenge_type(latest),
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


def _manual_refresh_argv(source_name: str, request_id: str) -> list[str]:
    base = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "refresh_sources.py"),
        "--lock-path",
        str(REFRESH_LOCK_PATH),
        "--source",
        source_name,
        "--run-request-id",
        request_id,
    ]
    if source_name != "immowelt-de":
        return base
    return [
        "/usr/bin/xvfb-run",
        "-a",
        "-s",
        "-screen 0 1920x1080x24",
        *base,
    ]


def _manual_refresh_env(source_name: str) -> dict[str, str] | None:
    if source_name != "immowelt-de":
        return None
    runtime_root = Path("/tmp/wohnwerk-admin-refresh")
    paths = {
        "HOME": runtime_root / "home",
        "XDG_CONFIG_HOME": runtime_root / "config",
        "XDG_CACHE_HOME": runtime_root / "cache",
        "XDG_RUNTIME_DIR": runtime_root / "runtime",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)

    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = "/var/cache/wohnwerk-playwright"
    env.update({key: str(value) for key, value in paths.items()})
    return env


def _health_redirect(notice: str, *, run_id: int | None = None) -> RedirectResponse:
    query: dict[str, str] = {"hinweis": notice}
    if run_id is not None:
        query["run_id"] = str(run_id)
    return RedirectResponse(f"/admin/health?{urlencode(query)}", status_code=303)


def _manual_run_id(db: Session, *, source_id: int, request_id: str) -> int | None:
    return db.scalar(
        select(CrawlRun.id)
        .where(
            CrawlRun.source_id == source_id,
            CrawlRun.run_metadata["manual_run_request_id"].as_string() == request_id,
        )
        .order_by(CrawlRun.id.desc())
        .limit(1)
    )


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

    paused_run_id = db.scalar(
        select(CrawlRun.id)
        .where(
            CrawlRun.source_id == source.id,
            CrawlRun.status == "paused",
            CrawlRun.finished_at.is_(None),
        )
        .order_by(CrawlRun.id.desc())
        .limit(1)
    )

    request_id = secrets.token_urlsafe(18)
    if source.name == "immowelt-de":
        # The readiness ticket belongs to one explicit manual request.
        # Scheduled refreshes never receive this request ID.
        bind_operator_readiness(request_id)
    try:
        process = subprocess.Popen(
            _manual_refresh_argv(source.name, request_id),
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env=_manual_refresh_env(source.name),
        )
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Quellenlauf konnte nicht gestartet werden: {exc}",
        ) from exc

    deadline = time.monotonic() + RUN_START_CONFIRM_TIMEOUT_SECONDS
    while True:
        run_id = _manual_run_id(db, source_id=source.id, request_id=request_id)
        if run_id is not None:
            notice = "run_resumed" if paused_run_id == run_id else "run_started"
            return _health_redirect(notice, run_id=run_id)

        returncode = process.poll()
        if returncode is not None:
            if returncode == MANUAL_RUN_BUSY_EXIT_CODE:
                return _health_redirect("refresh_busy")
            if returncode == MANUAL_RUN_DEFERRED_EXIT_CODE:
                return _health_redirect("run_deferred")
            return _health_redirect("run_failed")

        if time.monotonic() >= deadline:
            return _health_redirect("run_pending")
        time.sleep(RUN_START_POLL_SECONDS)


def _immowelt_run_context(
    db: Session,
    run_id: int,
) -> tuple[CrawlRun, Source]:
    run = db.get(CrawlRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Immowelt-Lauf nicht gefunden.")
    source = db.get(Source, run.source_id)
    if source is None or source.name != "immowelt-de":
        raise HTTPException(status_code=404, detail="Interaktive Übergabe ist nur für Immowelt verfügbar.")
    return run, source


def _immowelt_challenge_context(
    db: Session,
    run_id: int,
) -> tuple[CrawlRun, Source, dict, Path, Path]:
    run, source = _immowelt_run_context(db, run_id)
    if str(run.status) != "paused" or run.finished_at is not None:
        raise HTTPException(status_code=409, detail="Immowelt-Lauf wartet nicht auf eine Challenge.")
    active = dict(run.run_metadata or {}).get("active_challenge")
    if not isinstance(active, dict):
        raise HTTPException(status_code=409, detail="Der Lauf hat keine aktive Challenge.")
    challenge_type = _interactive_challenge_type(run)
    if challenge_type is None:
        raise HTTPException(status_code=409, detail="Die aktive Challenge ist nicht interaktiv.")
    try:
        state_dir, run_dir = challenge_state_for_run(run.id, active)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return run, source, active, state_dir, run_dir


@router.post("/sources/{source_id}/challenge/approve")
def approve_source_challenge(
    source_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
):
    source = db.get(Source, source_id)
    if source is None or source.name != "immowelt-de":
        raise HTTPException(status_code=404, detail="Immowelt-Quelle nicht gefunden.")
    run = db.scalar(
        select(CrawlRun)
        .where(
            CrawlRun.source_id == source.id,
            CrawlRun.status == "paused",
            CrawlRun.finished_at.is_(None),
        )
        .order_by(CrawlRun.id.desc())
        .limit(1)
    )
    if run is None:
        raise HTTPException(status_code=409, detail="Kein pausierter Immowelt-Lauf vorhanden.")

    active = dict(run.run_metadata or {}).get("active_challenge")
    if not isinstance(active, dict):
        raise HTTPException(status_code=409, detail="Der pausierte Lauf hat keine aktive Challenge.")
    run_dir = operator_run_dir(run.id)
    operator_state = read_operator_status(run_dir).get("state")
    if operator_state in {"armed", "active"}:
        # A pre-armed original live handoff is already in progress. Never
        # clear its screenshot/events or spawn a second browser worker.
        return RedirectResponse(f"/admin/challenges/{run.id}", status_code=303)
    live_waiting = operator_state == "awaiting_approval"
    stale_datadome_removed = 0
    try:
        if not live_waiting:
            stale_datadome_removed = prepare_fresh_operator_reverification(run.id, active)
        arm_operator_handoff(run.id, active)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    metadata = dict(run.run_metadata or {})
    metadata["operator_handoff_armed_at"] = datetime.now(UTC).isoformat()
    metadata["operator_reverification_stale_datadome_removed"] = stale_datadome_removed
    run.run_metadata = metadata
    db.commit()

    if live_waiting:
        # The original crawler is still holding its challenged BrowserContext/Page.
        # Its operator handler observes the approval asynchronously. Spawning another
        # refresh because activation takes >1.5s would race the live human handoff,
        # potentially replacing the very session the operator needs to complete.
        return RedirectResponse(f"/admin/challenges/{run.id}", status_code=303)

    request_id = secrets.token_urlsafe(18)
    try:
        subprocess.Popen(
            _manual_refresh_argv(source.name, request_id),
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env=_manual_refresh_env(source.name),
        )
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Interaktive Übergabe konnte nicht gestartet werden: {exc}",
        ) from exc

    return RedirectResponse(f"/admin/challenges/{run.id}", status_code=303)


@router.post("/health/immowelt-ready/arm")
def arm_immowelt_operator_ready(_: AdminDependency, __: CsrfDependency):
    try:
        arm_operator_readiness()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _health_redirect("operator_ready")


@router.post("/health/immowelt-ready/clear")
def clear_immowelt_operator_ready(_: AdminDependency, __: CsrfDependency):
    try:
        clear_operator_readiness()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _health_redirect("operator_ready_cleared")


@router.get("/health/immowelt-ready/status")
def immowelt_operator_ready_status(_: AdminDependency, db: DbDependency):
    status_payload = read_operator_readiness()
    run_id = status_payload.get("run_id")
    if isinstance(run_id, int):
        run = db.get(CrawlRun, run_id)
        if run is not None and _interactive_challenge_type(run) is not None:
            handoff = read_operator_status(operator_run_dir(run_id))
            if handoff.get("state") in {"armed", "active", "awaiting_approval"}:
                status_payload["handoff_state"] = handoff["state"]
                status_payload["live_run_id"] = run_id
                status_payload["browser_session"] = handoff.get("browser_session")
                # Countdown follows the live browser's actual deadline.
                if handoff.get("expires_at"):
                    status_payload["expires_at"] = handoff["expires_at"]
    return JSONResponse(status_payload, headers={"Cache-Control": "no-store"})


@router.get("/health/immowelt-runs")
def immowelt_run_diagnostics(
    _: AdminDependency,
    db: DbDependency,
    ids: str = Query(..., description="Comma-separated list of up to four CrawlRun IDs"),
):
    """Admin-only read-only historic run comparison, without challenge secrets."""
    parts = [part.strip() for part in ids.split(",")]
    if (
        not 1 <= len(parts) <= 4
        or any(not part.isdecimal() for part in parts)
        or len(set(parts)) != len(parts)
    ):
        raise HTTPException(status_code=400, detail="Erwartet werden 1–4 eindeutige Lauf-IDs.")

    rows = []
    for part in parts:
        run_id = int(part)
        run = db.get(CrawlRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"CrawlRun #{run_id} nicht gefunden.")
        source = db.get(Source, run.source_id)
        if source is None or source.name != "immowelt-de":
            raise HTTPException(status_code=404, detail="Nur Immowelt-Läufe verfügbar.")

        states = dict(
            db.execute(
                select(CrawlShardRun.status, func.count())
                .where(CrawlShardRun.crawl_run_id == run.id)
                .group_by(CrawlShardRun.status)
            ).all()
        )
        metadata = dict(run.run_metadata or {})
        history = metadata.get("challenge_history")
        recent_actions = (
            [
                {"action": value.get("action"), "at": value.get("at")}
                for value in history[-5:]
                if isinstance(value, dict)
            ]
            if isinstance(history, list)
            else []
        )
        active = metadata.get("active_challenge")
        active_type = None
        if isinstance(active, dict):
            challenge = active.get("challenge")
            if isinstance(challenge, dict):
                active_type = challenge.get("datadome_challenge_type")

        rows.append(
            {
                "id": run.id,
                "status": str(run.status),
                "coverage": str(run.coverage_status),
                "mode": str(run.mode),
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "pages_fetched": run.pages_fetched,
                "items_seen": run.items_seen,
                "items_new": run.items_new,
                "items_updated": run.items_updated,
                "items_disappeared": run.items_disappeared,
                "shard_status_counts": states,
                "last_activity_at": metadata.get("last_activity_at"),
                "active_challenge_type": active_type,
                "challenge_handoff_count": metadata.get("challenge_handoff_count"),
                "recent_challenge_actions": recent_actions,
            }
        )
    return JSONResponse({"runs": rows}, headers={"Cache-Control": "no-store"})


@router.get("/challenges/{run_id}")
def challenge_handoff_page(
    run_id: int,
    request: Request,
    _: AdminDependency,
    db: DbDependency,
):
    run, _source, _active, _state_dir, _run_dir = _immowelt_challenge_context(db, run_id)
    return templates.TemplateResponse(
        request=request,
        name="admin_challenge_handoff.html",
        context={
            "run": run,
            "csrf_token": _csrf_token(),
        },
    )


@router.get("/challenges/{run_id}/status")
def challenge_handoff_status(
    run_id: int,
    _: AdminDependency,
    db: DbDependency,
):
    _run, _source = _immowelt_run_context(db, run_id)
    run_dir = operator_run_dir(run_id)
    return JSONResponse(read_operator_status(run_dir), headers={"Cache-Control": "no-store"})


@router.get("/challenges/{run_id}/frame")
def challenge_handoff_frame(
    run_id: int,
    _: AdminDependency,
    db: DbDependency,
):
    run, _source = _immowelt_run_context(db, run_id)
    run_dir = operator_run_dir(run_id)
    frame = operator_frame_path(run_dir)
    if not frame.is_file():
        active = dict(run.run_metadata or {}).get("active_challenge")
        if isinstance(active, dict):
            try:
                state_dir, _ = challenge_state_for_run(run.id, active)
            except ValueError:
                state_dir = None
            handoff = active.get("handoff_state")
            screenshot = handoff.get("screenshot_path") if isinstance(handoff, dict) else None
            if screenshot and state_dir is not None:
                candidate = Path(str(screenshot)).resolve()
                try:
                    candidate.relative_to(state_dir)
                except ValueError:
                    candidate = None
                if candidate is not None and candidate.is_file():
                    frame = candidate
    if not frame.is_file():
        raise HTTPException(status_code=404, detail="Noch kein Challenge-Bild verfügbar.")
    return FileResponse(
        frame,
        media_type="image/png",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.post("/challenges/{run_id}/pointer")
def challenge_handoff_pointer(
    run_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
    phase: str = Form(),
    x: float = Form(0.0),
    y: float = Form(0.0),
):
    _run, _source, _active, _state_dir, run_dir = _immowelt_challenge_context(db, run_id)
    try:
        enqueue_operator_pointer(run_dir, phase=phase, x=x, y=y)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True})


@router.post("/challenges/{run_id}/cancel")
def challenge_handoff_cancel(
    run_id: int,
    _: AdminDependency,
    __: CsrfDependency,
    db: DbDependency,
):
    _run, _source, _active, _state_dir, run_dir = _immowelt_challenge_context(db, run_id)
    enqueue_operator_pointer(run_dir, phase="cancel")
    return RedirectResponse("/admin/health?hinweis=challenge_cancelled", status_code=303)


@router.get("/health")
def admin_health_page(
    request: Request,
    _: AdminDependency,
    db: DbDependency,
    hinweis: str | None = None,
    run_id: int | None = None,
):
    notice = NOTICE_LABELS.get(hinweis or "")
    if hinweis == "run_started" and run_id is not None:
        notice = f"Manueller Quellenlauf #{run_id} wurde gestartet."
    elif hinweis == "run_resumed" and run_id is not None:
        notice = f"Pausierter Quellenlauf #{run_id} wurde manuell fortgesetzt."
    return templates.TemplateResponse(
        request=request,
        name="admin_health.html",
        context={
            "snapshot": collect_ops_snapshot(db),
            "operator_readiness": read_operator_readiness(),
            "csrf_token": _csrf_token(),
            "notice": notice,
        },
    )
