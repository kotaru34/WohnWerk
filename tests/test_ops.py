from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.admin import require_admin
from app.database import get_db
from app.main import app
from app.models import CoverageStatus, RunStatus
from app.ops import JobSourceValueRow, OpsSnapshot, SourceOpsRow, source_ops_state


def _source(**overrides):
    values = {
        "enabled": True,
        "coverage_status": CoverageStatus.OK,
        "poll_interval_minutes": 60,
        "last_success_at": datetime(2026, 8, 30, 10, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_source_ops_state_flags_stale_and_failed_sources() -> None:
    now = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)

    assert source_ops_state(
        _source(last_success_at=now - timedelta(minutes=20)),
        SimpleNamespace(status=RunStatus.SUCCESS),
        0,
        now=now,
    ) == "ok"
    assert source_ops_state(
        _source(last_success_at=now - timedelta(hours=4)),
        SimpleNamespace(status=RunStatus.SUCCESS),
        0,
        now=now,
    ) == "veraltet"
    assert source_ops_state(
        _source(),
        SimpleNamespace(status=RunStatus.FAILED),
        0,
        now=now,
    ) == "warnung"
    assert source_ops_state(
        _source(enabled=False),
        None,
        0,
        now=now,
    ) == "deaktiviert"


def test_legacy_bounded_partial_without_failed_shards_is_not_a_warning() -> None:
    now = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)
    legacy_bounded = SimpleNamespace(
        status=RunStatus.PARTIAL,
        shards_total=9,
        shards_completed=9,
        shards_failed=0,
    )
    genuine_partial = SimpleNamespace(
        status=RunStatus.PARTIAL,
        shards_total=9,
        shards_completed=8,
        shards_failed=1,
    )

    assert source_ops_state(
        _source(last_success_at=now - timedelta(minutes=20)),
        legacy_bounded,
        0,
        now=now,
    ) == "ok"
    assert source_ops_state(
        _source(last_success_at=now - timedelta(minutes=20)),
        genuine_partial,
        0,
        now=now,
    ) == "warnung"


def test_job_source_value_yield() -> None:
    row = JobSourceValueRow(
        name="example-source",
        enabled=True,
        active_accepted_listings=15,
        catalog_jobs=12,
        exclusive_jobs=9,
        shared_jobs=3,
        latest_candidates=20,
        latest_accepted=5,
        latest_rejected=15,
    )

    assert row.latest_yield_percent == 25.0


def test_admin_health_page_renders_snapshot(monkeypatch) -> None:
    snapshot = OpsSnapshot(
        active_properties=1234,
        active_jobs=88,
        unresolved_job_locations=3,
        enabled_sources=7,
        sources=(
            SourceOpsRow(
                name="example-source",
                category="job",
                enabled=True,
                state="ok",
                coverage_status="ok",
                poll_interval_minutes=60,
                last_success_at=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
                latest_run_id=42,
                latest_mode="incremental",
                latest_status="success",
                latest_started_at=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
                latest_items_seen=15,
                latest_shards_failed=0,
                failing_shards=0,
                last_error=None,
            ),
        ),
        unresolved_labels=(("Traboch", 2),),
        visible_jobs=77,
        job_sources=(
            JobSourceValueRow(
                name="example-source",
                enabled=True,
                active_accepted_listings=15,
                catalog_jobs=12,
                exclusive_jobs=9,
                shared_jobs=3,
                latest_candidates=20,
                latest_accepted=5,
                latest_rejected=15,
            ),
        ),
    )

    def override_db():
        yield object()

    monkeypatch.setattr("app.ops.collect_ops_snapshot", lambda _db: snapshot)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    try:
        with TestClient(app) as client:
            page = client.get("/admin/health")
            assert page.status_code == 200
            assert "Betriebsübersicht" in page.text
            assert "1234" in page.text
            assert "77" in page.text
            assert "Wert der Stellenquellen" in page.text
            assert "25.0 %" in page.text
            assert "example-source" in page.text
            assert "Traboch" in page.text
    finally:
        app.dependency_overrides.clear()