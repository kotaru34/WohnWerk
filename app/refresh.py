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
    failure_isolated: bool = False
    operational_note: str | None = None


@dataclass(frozen=True, slots=True)
class DueSourceRun:
    plan: SourceRefreshPlan
    reconciliation: bool

    @property
    def mode(self) -> str:
        return CrawlMode.RECONCILIATION if self.reconciliation else CrawlMode.INCREMENTAL


MANUAL_RUN_BUSY_EXIT_CODE = 75
MANUAL_RUN_DEFERRED_EXIT_CODE = 76
MANUAL_RUN_REQUEST_ENV = "WOHNWERK_MANUAL_RUN_REQUEST_ID"


# Only Germany property sources validated in production belong here. Discovery/frontier sources deliberately
# have no reconciliation authority: disappearing from a first-page/search frontier is not
# evidence that an advert has closed. Disabled candidate sources may be registered ahead of
# enablement so an operator can activate a production-validated tenant without another
# scheduler code change; disabled Source rows are ignored by due_source_runs().
SOURCE_REFRESH_PLANS: tuple[SourceRefreshPlan, ...] = (
    # ImmoScout24 DE remains explicitly paused/fail-closed after the public frontend
    # required a human challenge. Do not schedule it until its transport is revalidated.
    # Immowelt DE is currently a bounded discovery source. It remains incremental-only and
    # its temporary browser/access failures are source-isolated so they cannot fail the
    # other German property acquisition runs.
    SourceRefreshPlan(
        "immowelt-de",
        "scripts/run_immowelt_de.py",
        False,
        failure_isolated=True,
    ),
    # Kleinanzeigen is intentionally a bounded newest-first frontier and can never
    # prove disappearance. VON POLL has deterministic state shards and can reconcile
    # only when every public page is traversed below its safety cap.
    SourceRefreshPlan(
        "kleinanzeigen-de",
        "scripts/run_kleinanzeigen_de.py",
        False,
        failure_isolated=True,
    ),
    SourceRefreshPlan(
        "engel-voelkers-de",
        "scripts/run_engel_voelkers_de.py",
        False,
        failure_isolated=True,
    ),
    # RE/MAX DE is intentionally unscheduled: target-host live validation on
    # 2026-10-03 reached a Cloudflare Turnstile verification page. The adapter remains
    # for diagnostics and fails closed on that challenge; no bypass is attempted.
    SourceRefreshPlan(
        "iad-de",
        "scripts/run_iad_de.py",
        False,
        failure_isolated=True,
    ),
    SourceRefreshPlan(
        "falc-de",
        "scripts/run_falc_de.py",
        False,
        failure_isolated=True,
    ),
)

# These adapters stay out of automatic scheduling but remain available to an authenticated
# operator for an explicit diagnostic/manual run. They fail closed when their public frontend
# presents a human-verification boundary; the admin UI surfaces that reason from the run.
MANUAL_SOURCE_RUN_PLANS: tuple[SourceRefreshPlan, ...] = (
    # These two independent public frontiers are diagnostics only until real
    # provider fetches confirm stable card parsing. Never auto-schedule them.
    SourceRefreshPlan(
        "ohne-makler-de", "scripts/run_ohne_makler_de.py", False,
        failure_isolated=True,
        operational_note=(
            "Neue Quelle: Karten allein sind kein Hausnachweis. Vor Automatik "
            "öffentliche Detailseiten (Bestandsgebäude, Grundstück und Gesamtpreis) "
            "und Nutzungsbedingungen prüfen; nur manuelle Diagnose."
        ),
    ),
    SourceRefreshPlan(
        "immobilien-de", "scripts/run_immobilien_de.py", False,
        failure_isolated=True,
        operational_note=(
            "Neue Quelle: Karten allein sind kein Hausnachweis. Vor Automatik "
            "öffentliche Detailseiten (Bestandsgebäude, Grundstück und Gesamtpreis) "
            "und Nutzungsbedingungen prüfen; nur manuelle Diagnose."
        ),
    ),
    SourceRefreshPlan(
        "remax-de",
        "scripts/run_remax_de.py",
        False,
        failure_isolated=True,
        operational_note=(
            "Automatik pausiert: der Zielhost zeigte zuletzt Cloudflare Turnstile. "
            "Manueller Diagnose-Lauf ist möglich; kein Challenge-Bypass."
        ),
    ),
    SourceRefreshPlan(
        "immoscout24-de",
        "scripts/run_immoscout24_de.py",
        False,
        failure_isolated=True,
        operational_note=(
            "Automatik pausiert: der öffentliche ImmoScout24-Frontend-Pfad verlangte "
            "zuletzt eine menschliche Challenge. Manueller Diagnose-Lauf bleibt fail-closed."
        ),
    ),
    SourceRefreshPlan(
        "von-poll-de",
        "scripts/run_von_poll_de.py",
        False,
        failure_isolated=True,
        operational_note=(
            "Automatik pausiert: der Zielhost erhielt zuletzt HTTP 403. "
            "Manueller Diagnose-Lauf bleibt fail-closed, bis ein unterstützter "
            "öffentlicher Transport erneut validiert wurde."
        ),
    ),
)


def source_run_plan(source_name: str) -> SourceRefreshPlan | None:
    for plan in (*SOURCE_REFRESH_PLANS, *MANUAL_SOURCE_RUN_PLANS):
        if plan.source_name == source_name:
            return plan
    return None


def source_is_scheduled(source_name: str) -> bool:
    return any(plan.source_name == source_name for plan in SOURCE_REFRESH_PLANS)


def source_operational_note(source_name: str) -> str | None:
    plan = source_run_plan(source_name)
    return plan.operational_note if plan is not None else None


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
