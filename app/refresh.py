from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CrawlMode, CrawlRun, Source


@dataclass(frozen=True, slots=True)
class SourceRefreshPlan:
    source_name: str
    script: str
    supports_reconciliation: bool


@dataclass(frozen=True, slots=True)
class DueSourceRun:
    plan: SourceRefreshPlan
    reconciliation: bool

    @property
    def mode(self) -> str:
        return CrawlMode.RECONCILIATION if self.reconciliation else CrawlMode.INCREMENTAL


# Only sources validated in production belong here. Discovery/frontier sources deliberately
# have no reconciliation authority: disappearing from a first-page/search frontier is not
# evidence that an advert has closed. Disabled candidate sources may be registered ahead of
# enablement so an operator can activate a production-validated tenant without another
# scheduler code change; disabled Source rows are ignored by due_source_runs().
SOURCE_REFRESH_PLANS: tuple[SourceRefreshPlan, ...] = (
    SourceRefreshPlan("immmo.at", "scripts/run_immmo.py", True),
    SourceRefreshPlan("sreal.at", "scripts/run_sreal.py", True),
    # ImmoScout24 DE remains explicitly paused/fail-closed after the public frontend
    # required a human challenge. Do not schedule it until its transport is revalidated.
    # Immowelt DE is currently a bounded discovery source: its source-wide 403 gate makes
    # exhaustive reconciliation non-authoritative, while fair incremental runs can safely
    # continue filling the frontier over time.
    SourceRefreshPlan("immowelt-de", "scripts/run_immowelt_de.py", False),
    SourceRefreshPlan("lever-public-postings", "scripts/run_lever_jobs.py", True),
    SourceRefreshPlan(
        "greenhouse-public-job-board",
        "scripts/run_greenhouse_jobs.py",
        True,
    ),
    SourceRefreshPlan("personio-public-xml", "scripts/run_personio_jobs.py", True),
    SourceRefreshPlan(
        "smartrecruiters-public-postings",
        "scripts/run_smartrecruiters_jobs.py",
        True,
    ),
    SourceRefreshPlan(
        "successfactors-public-career-site",
        "scripts/run_successfactors_jobs.py",
        True,
    ),
    SourceRefreshPlan("tgw-direct-careers", "scripts/run_tgw_jobs.py", True),
    SourceRefreshPlan("palfinger-direct-careers", "scripts/run_palfinger_jobs.py", True),
    SourceRefreshPlan("workday-public-cxs", "scripts/run_workday_jobs.py", False),
    SourceRefreshPlan("karriere.at", "scripts/run_karriere_at_jobs.py", False),
    SourceRefreshPlan("jobs.at", "scripts/run_jobs_at_jobs.py", False),
    SourceRefreshPlan("stepstone.at", "scripts/run_stepstone_at_jobs.py", False),
    SourceRefreshPlan("willhaben-jobs", "scripts/run_willhaben_jobs.py", False),
    SourceRefreshPlan("adzuna-api-de", "scripts/run_adzuna_de_jobs.py", False),
    SourceRefreshPlan(
        "arbeitsagentur-jobsuche-de",
        "scripts/run_arbeitsagentur_jobs.py",
        False,
    ),
)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _elapsed(reference: datetime | None, *, now: datetime) -> timedelta | None:
    aware = _aware(reference)
    return None if aware is None else now - aware


def _latest_time(*values: datetime | None) -> datetime | None:
    aware = [item for value in values if (item := _aware(value)) is not None]
    return max(aware) if aware else None


def _reconciliation_interval(source: Source) -> timedelta | None:
    value = (source.config or {}).get("reconciliation_interval_hours")
    if value is None:
        return None
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return None
    if hours <= 0:
        return None
    return timedelta(hours=hours)


def _latest_reconciliation_attempt(session: Session, source_id: int) -> datetime | None:
    return session.scalar(
        select(CrawlRun.started_at)
        .where(
            CrawlRun.source_id == source_id,
            CrawlRun.mode == CrawlMode.RECONCILIATION,
        )
        .order_by(CrawlRun.started_at.desc())
        .limit(1)
    )


def source_due_run(
    session: Session,
    source: Source,
    plan: SourceRefreshPlan,
    *,
    now: datetime | None = None,
    reconciliation_retry_minutes: int = 180,
) -> DueSourceRun | None:
    """Choose at most one safe run for a source at this scheduler tick."""
    if not source.enabled:
        return None

    current = (now or datetime.now(UTC)).astimezone(UTC)
    reconciliation_interval = _reconciliation_interval(source)
    if plan.supports_reconciliation and reconciliation_interval is not None:
        since_ok_reconciliation = _elapsed(source.last_reconciliation_at, now=current)
        reconciliation_due = (
            since_ok_reconciliation is None
            or since_ok_reconciliation >= reconciliation_interval
        )
        if reconciliation_due:
            last_attempt = _latest_reconciliation_attempt(session, source.id)
            since_attempt = _elapsed(last_attempt, now=current)
            retry_after = timedelta(minutes=max(1, reconciliation_retry_minutes))
            if since_attempt is None or since_attempt >= retry_after:
                return DueSourceRun(plan=plan, reconciliation=True)

    # A complete reconciliation is also a fresh source scan. Do not immediately run an
    # incremental scan just because last_incremental_at predates the full reconciliation.
    latest_scan = _latest_time(source.last_incremental_at, source.last_reconciliation_at)
    poll_interval = timedelta(minutes=max(1, source.poll_interval_minutes))
    since_scan = _elapsed(latest_scan, now=current)
    if since_scan is None or since_scan >= poll_interval:
        return DueSourceRun(plan=plan, reconciliation=False)
    return None


def due_source_runs(
    session: Session,
    *,
    now: datetime | None = None,
    reconciliation_retry_minutes: int = 180,
) -> list[DueSourceRun]:
    sources = {
        source.name: source
        for source in session.scalars(
            select(Source).where(Source.enabled.is_(True)).order_by(Source.id)
        )
    }
    due: list[DueSourceRun] = []
    for plan in SOURCE_REFRESH_PLANS:
        source = sources.get(plan.source_name)
        if source is None:
            continue
        selected = source_due_run(
            session,
            source,
            plan,
            now=now,
            reconciliation_retry_minutes=reconciliation_retry_minutes,
        )
        if selected is not None:
            due.append(selected)
    return due
