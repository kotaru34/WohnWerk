from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.admin import require_admin, require_csrf
from app.database import get_db
from app.main import app
from app.models import CoverageStatus, RunStatus
from app.ops import (
    JobSourceValueRow,
    OpsSnapshot,
    SourceOpsRow,
    source_ops_reason,
    source_ops_state,
    split_unresolved_location_labels,
)
from app.refresh_runtime import REFRESH_LOCK_PATH


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


def test_source_ops_reason_explains_manual_only_and_failed_runs() -> None:
    now = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)

    manual = _source(last_success_at=now - timedelta(minutes=10))
    assert source_ops_state(
        manual,
        SimpleNamespace(status=RunStatus.SUCCESS),
        0,
        now=now,
        scheduled=False,
        runnable=True,
    ) == "warnung"
    assert "Turnstile" in source_ops_reason(
        manual,
        SimpleNamespace(status=RunStatus.SUCCESS),
        0,
        (),
        now=now,
        scheduled=False,
        runnable=True,
        operational_note="Automatik pausiert: Cloudflare Turnstile.",
    )

    failed = SimpleNamespace(
        id=77,
        status=RunStatus.FAILED,
        error="HTTP 403 challenge",
        started_at=now - timedelta(minutes=5),
        shards_failed=1,
        shards_total=1,
        shards_completed=0,
    )
    reason = source_ops_reason(
        _source(),
        failed,
        1,
        ("HTTP 403 challenge",),
        now=now,
    )
    assert "Lauf #77 fehlgeschlagen" in reason
    assert "HTTP 403 challenge" in reason


def test_source_ops_reason_explains_intentional_frontier_degraded_coverage() -> None:
    now = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)
    source = _source(
        coverage_status=CoverageStatus.DEGRADED,
        last_success_at=now - timedelta(minutes=10),
    )
    latest = SimpleNamespace(status=RunStatus.SUCCESS, error=None)

    reason = source_ops_reason(
        source,
        latest,
        0,
        (),
        now=now,
        supports_reconciliation=False,
    )

    assert "Letzter Lauf erfolgreich" in reason
    assert "Frontier-Scan" in reason
    assert "Disappearance-Authority" in reason


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


def test_ops_geo_backlog_separates_non_point_scopes() -> None:
    concrete, non_point = split_unresolved_location_labels(
        (
            ("Traboch", 2),
            ("Kärnten", 1),
            ("Wels-Land", 1),
            ("Bezirk Wels-Land", 1),
            ("Graz Umgebung-West", 1),
            ("österreichweit", 1),
        )
    )

    assert concrete == (("Traboch", 2),)
    assert non_point == (
        ("Kärnten", 1),
        ("Wels-Land", 1),
        ("Bezirk Wels-Land", 1),
        ("Graz Umgebung-West", 1),
        ("österreichweit", 1),
    )


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
        unresolved_job_locations=2,
        enabled_sources=7,
        sources=(
            SourceOpsRow(
                id=7,
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
                state_reason="Letzter Lauf und Coverage sind ohne aktuellen Fehler.",
                latest_error=None,
                latest_pages_fetched=3,
                latest_items_new=2,
                latest_items_updated=1,
                latest_items_disappeared=0,
                latest_shards_total=1,
                latest_shards_completed=1,
                shard_errors=(),
                scheduled=True,
                runnable=True,
                operational_note=None,
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
        non_point_job_locations=5,
        non_point_labels=(
            ("Kärnten", 1),
            ("Wels-Land", 1),
            ("Bezirk Wels-Land", 1),
            ("Graz Umgebung-West", 1),
            ("österreichweit", 1),
        ),
    )

    def override_db():
        yield object()

    monkeypatch.setattr("app.ops.collect_ops_snapshot", lambda _db: snapshot)
    monkeypatch.setattr("app.ops._csrf_token", lambda: "test-csrf")
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
            assert "Letzter Lauf und Coverage" in page.text
            assert 'class="source-list"' in page.text
            assert 'class="source-card"' in page.text
            assert "Details &amp; Diagnose" in page.text
            assert "Coverage ok" in page.text
            assert "3 Seiten" in page.text
            assert "1/1 Shards" in page.text
            assert "Jetzt ausführen" in page.text
            assert "Deaktivieren" in page.text
            assert "konkrete ungeocodierte Job-Orte" in page.text
            assert "Noch nicht aufgelöste konkrete Ortsangaben" in page.text
            assert "Traboch" in page.text
            assert "Regionale / landesweite Ortsangaben" in page.text
            assert "Kärnten" in page.text
            assert "österreichweit" in page.text
    finally:
        app.dependency_overrides.clear()



class _SourceControlDb:
    def __init__(self, source):
        self.source = source
        self.commits = 0

    def get(self, model, source_id):
        del model
        return self.source if source_id == self.source.id else None

    def scalar(self, _statement):
        return None

    def commit(self):
        self.commits += 1


def test_admin_can_disable_and_enable_source() -> None:
    source = SimpleNamespace(id=9, name="falc-de", enabled=True)
    db = _SourceControlDb(source)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[require_csrf] = lambda: None
    try:
        with TestClient(app) as client:
            disabled = client.post(
                "/admin/sources/9/enabled",
                data={"enabled": "0"},
                follow_redirects=False,
            )
            assert disabled.status_code == 303
            assert disabled.headers["location"].endswith("hinweis=source_disabled")
            assert source.enabled is False

            enabled = client.post(
                "/admin/sources/9/enabled",
                data={"enabled": "1"},
                follow_redirects=False,
            )
            assert enabled.status_code == 303
            assert enabled.headers["location"].endswith("hinweis=source_enabled")
            assert source.enabled is True
            assert db.commits == 2
    finally:
        app.dependency_overrides.clear()


def test_admin_run_now_waits_for_correlated_crawl_run(monkeypatch) -> None:
    source = SimpleNamespace(id=10, name="falc-de", enabled=True)
    db = _SourceControlDb(source)
    calls = []

    def override_db():
        yield db

    class _Process:
        pid = 123

        def poll(self):
            return None

    def fake_popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return _Process()

    monkeypatch.setattr(
        "app.ops.source_run_plan",
        lambda name: SimpleNamespace(source_name=name) if name == "falc-de" else None,
    )
    monkeypatch.setattr("app.ops.subprocess.Popen", fake_popen)
    monkeypatch.setattr("app.ops._manual_run_id", lambda *_args, **_kwargs: 321)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[require_csrf] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.post(
                "/admin/sources/10/run",
                follow_redirects=False,
            )

        assert response.status_code == 303
        assert "hinweis=run_started" in response.headers["location"]
        assert "run_id=321" in response.headers["location"]
        assert len(calls) == 1
        argv, kwargs = calls[0]
        assert "--lock-path" in argv
        assert argv[argv.index("--lock-path") + 1] == str(REFRESH_LOCK_PATH)
        assert "--source" in argv
        assert argv[argv.index("--source") + 1] == "falc-de"
        assert "--run-request-id" in argv
        assert argv[argv.index("--run-request-id") + 1]
        assert any(item.endswith("scripts/refresh_sources.py") for item in argv)
        assert kwargs["start_new_session"] is True
        assert kwargs["close_fds"] is True
    finally:
        app.dependency_overrides.clear()



def test_admin_run_now_surfaces_resumed_paused_run(monkeypatch) -> None:
    source = SimpleNamespace(id=10, name="immowelt-de", enabled=True)

    class _PausedDb(_SourceControlDb):
        def __init__(self, source):
            super().__init__(source)
            self.scalar_calls = 0

        def scalar(self, _statement):
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                return None
            if self.scalar_calls == 2:
                return 444
            return None

    db = _PausedDb(source)

    def override_db():
        yield db

    class _Process:
        def poll(self):
            return None

    monkeypatch.setattr(
        "app.ops.source_run_plan",
        lambda name: SimpleNamespace(source_name=name) if name == "immowelt-de" else None,
    )
    monkeypatch.setattr("app.ops.subprocess.Popen", lambda *_args, **_kwargs: _Process())
    monkeypatch.setattr("app.ops._manual_run_id", lambda *_args, **_kwargs: 444)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[require_csrf] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.post(
                "/admin/sources/10/run",
                follow_redirects=False,
            )

        assert response.status_code == 303
        assert "hinweis=run_resumed" in response.headers["location"]
        assert "run_id=444" in response.headers["location"]
    finally:
        app.dependency_overrides.clear()

def test_admin_run_now_reports_global_refresh_lock_conflict(monkeypatch) -> None:
    source = SimpleNamespace(id=10, name="falc-de", enabled=True)
    db = _SourceControlDb(source)

    def override_db():
        yield db

    class _Process:
        def poll(self):
            return 75

    monkeypatch.setattr(
        "app.ops.source_run_plan",
        lambda name: SimpleNamespace(source_name=name) if name == "falc-de" else None,
    )
    monkeypatch.setattr("app.ops.subprocess.Popen", lambda *_args, **_kwargs: _Process())
    monkeypatch.setattr("app.ops._manual_run_id", lambda *_args, **_kwargs: None)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[require_csrf] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.post(
                "/admin/sources/10/run",
                follow_redirects=False,
            )

        assert response.status_code == 303
        assert response.headers["location"].endswith("hinweis=refresh_busy")
    finally:
        app.dependency_overrides.clear()


def test_admin_health_run_started_notice_includes_run_id(monkeypatch) -> None:
    snapshot = OpsSnapshot(
        active_properties=0,
        active_jobs=0,
        unresolved_job_locations=0,
        enabled_sources=0,
        sources=(),
        unresolved_labels=(),
    )

    def override_db():
        yield object()

    monkeypatch.setattr("app.ops.collect_ops_snapshot", lambda _db: snapshot)
    monkeypatch.setattr("app.ops._csrf_token", lambda: "test-csrf")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    try:
        with TestClient(app) as client:
            page = client.get("/admin/health?hinweis=run_started&run_id=321")

        assert page.status_code == 200
        assert "Manueller Quellenlauf #321 wurde gestartet." in page.text
    finally:
        app.dependency_overrides.clear()



def test_admin_health_run_resumed_notice_includes_run_id(monkeypatch) -> None:
    snapshot = OpsSnapshot(
        active_properties=0,
        active_jobs=0,
        unresolved_job_locations=0,
        enabled_sources=0,
        sources=(),
        unresolved_labels=(),
    )

    def override_db():
        yield object()

    monkeypatch.setattr("app.ops.collect_ops_snapshot", lambda _db: snapshot)
    monkeypatch.setattr("app.ops._csrf_token", lambda: "test-csrf")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    try:
        with TestClient(app) as client:
            page = client.get("/admin/health?hinweis=run_resumed&run_id=444")

        assert page.status_code == 200
        assert "Pausierter Quellenlauf #444 wurde manuell fortgesetzt." in page.text
    finally:
        app.dependency_overrides.clear()
