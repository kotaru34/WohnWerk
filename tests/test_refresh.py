from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Source
from app.refresh import SOURCE_REFRESH_PLANS, SourceRefreshPlan, source_due_run

NOW = datetime(2026, 8, 28, 15, 0, tzinfo=UTC)


def _source(
    *,
    enabled: bool = True,
    poll_minutes: int = 60,
    reconciliation_hours: int | None = 24,
    last_incremental_at: datetime | None = None,
    last_reconciliation_at: datetime | None = None,
) -> Source:
    return Source(
        id=1,
        name="example",
        category="job",
        adapter="example.Adapter",
        enabled=enabled,
        poll_interval_minutes=poll_minutes,
        config={"reconciliation_interval_hours": reconciliation_hours},
        last_incremental_at=last_incremental_at,
        last_reconciliation_at=last_reconciliation_at,
    )


def test_authoritative_source_prefers_due_reconciliation(monkeypatch) -> None:
    source = _source(
        last_incremental_at=NOW - timedelta(minutes=90),
        last_reconciliation_at=NOW - timedelta(hours=25),
    )
    plan = SourceRefreshPlan("example", "scripts/example.py", True)
    monkeypatch.setattr(
        "app.refresh._latest_reconciliation_attempt",
        lambda *_args, **_kwargs: NOW - timedelta(hours=25),
    )

    selected = source_due_run(object(), source, plan, now=NOW)

    assert selected is not None
    assert selected.reconciliation is True


def test_recent_failed_reconciliation_uses_incremental_when_that_is_due(monkeypatch) -> None:
    source = _source(
        last_incremental_at=NOW - timedelta(minutes=90),
        last_reconciliation_at=NOW - timedelta(hours=25),
    )
    plan = SourceRefreshPlan("example", "scripts/example.py", True)
    monkeypatch.setattr(
        "app.refresh._latest_reconciliation_attempt",
        lambda *_args, **_kwargs: NOW - timedelta(minutes=30),
    )

    selected = source_due_run(object(), source, plan, now=NOW)

    assert selected is not None
    assert selected.reconciliation is False


def test_reconciliation_counts_as_fresh_scan_for_incremental(monkeypatch) -> None:
    source = _source(
        last_incremental_at=NOW - timedelta(hours=8),
        last_reconciliation_at=NOW - timedelta(minutes=20),
    )
    plan = SourceRefreshPlan("example", "scripts/example.py", True)
    monkeypatch.setattr(
        "app.refresh._latest_reconciliation_attempt",
        lambda *_args, **_kwargs: NOW - timedelta(minutes=20),
    )

    assert source_due_run(object(), source, plan, now=NOW) is None


def test_frontier_source_never_requests_reconciliation() -> None:
    source = _source(
        poll_minutes=180,
        reconciliation_hours=None,
        last_incremental_at=NOW - timedelta(hours=4),
        last_reconciliation_at=None,
    )
    plan = SourceRefreshPlan("example", "scripts/example.py", False)

    selected = source_due_run(object(), source, plan, now=NOW)

    assert selected is not None
    assert selected.reconciliation is False


def test_disabled_source_is_never_due() -> None:
    source = _source(enabled=False)
    plan = SourceRefreshPlan("example", "scripts/example.py", True)

    assert source_due_run(object(), source, plan, now=NOW) is None


def test_german_property_sources_are_scheduled_with_fail_closed_reconciliation() -> None:
    plans = {plan.source_name: plan for plan in SOURCE_REFRESH_PLANS}

    assert plans["immoscout24-de"].supports_reconciliation is True
    assert plans["immowelt-de"].supports_reconciliation is True
