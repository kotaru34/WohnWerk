from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.admin import require_admin, require_csrf
from app.crawling.challenge import ChallengeRequest, ChallengeResult
from app.crawling.immowelt_operator_handoff import (
    ImmoweltOperatorChallengeHandler,
    operator_run_dir,
    read_operator_status,
    register_live_operator_session,
    unregister_live_operator_session,
)
from app.crawling.immowelt_operator_ready import (
    OPERATOR_READY_TTL,
    arm_operator_readiness,
    bind_operator_readiness,
    clear_operator_readiness,
    consume_operator_readiness,
    read_operator_readiness,
    ready_path,
)
from app.database import get_db
from app.main import app
from app.refresh import MANUAL_RUN_REQUEST_ENV


def _request(root: Path) -> ChallengeRequest:
    state_dir = root / "run-123" / "shard-7" / "handoff-1"
    state_dir.mkdir(parents=True)
    return ChallengeRequest(
        source="immowelt-de",
        run_id=123,
        shard_id=7,
        shard_key="test",
        shard_params={},
        mode="incremental",
        reason="manual DataDome",
        challenge={
            "requested_url": "https://www.immowelt.de/classified-search?page=1",
            "datadome_challenge_type": "fe",
        },
        resume_cursor={"resume_page": 1},
        handoff_state={"state_dir": str(state_dir)},
    )


def test_ready_ticket_requires_exact_manual_identity_and_expires(tmp_path: Path) -> None:
    root = tmp_path / "immowelt"
    before = datetime.now(UTC)
    armed = arm_operator_readiness(root, now=before)
    assert armed["state"] == "ready"
    assert stat.S_IMODE(ready_path(root).stat().st_mode) == 0o600
    assert not bind_operator_readiness("")
    assert bind_operator_readiness("manual-one", root)
    assert read_operator_readiness(root)["state"] == "bound"
    assert not bind_operator_readiness("manual-two", root)
    assert not consume_operator_readiness(123, root, request_id="")
    assert not consume_operator_readiness(123, root, request_id="manual-two")
    assert consume_operator_readiness(123, root, request_id="manual-one")
    assert not consume_operator_readiness(124, root, request_id="manual-one")
    status = read_operator_readiness(root)
    assert status["state"] == "consumed"
    assert status["run_id"] == 123
    assert "manual_request_id" not in json.dumps(status)
    assert "manual-one" not in ready_path(root).read_text()
    assert status["expires_at"] > before.isoformat()
    with pytest.raises(ValueError, match="attached"):
        arm_operator_readiness(root)
    with pytest.raises(ValueError, match="cancelled"):
        clear_operator_readiness(root)
    assert read_operator_readiness(root, now=before + timedelta(days=1))["state"] == "expired"


def test_clear_expired_ready_then_rearm(tmp_path: Path) -> None:
    root = tmp_path / "immowelt"
    t = datetime.now(UTC)
    arm_operator_readiness(root, now=t - OPERATOR_READY_TTL - timedelta(seconds=1))
    assert read_operator_readiness(root)["state"] == "expired"
    arm_operator_readiness(root, now=t)
    clear_operator_readiness(root)
    assert read_operator_readiness(root)["state"] == "idle"


@pytest.mark.asyncio
async def test_prearmed_manual_handoff_uses_original_live_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "immowelt"
    request = _request(root)
    arm_operator_readiness(root)
    assert bind_operator_readiness("manual-test", root)
    monkeypatch.setenv(MANUAL_RUN_REQUEST_ENV, "manual-test")

    class Fallback:
        async def handle(self, _request):
            raise AssertionError("Live human handoff must not fall back to restored browser")

    handler = ImmoweltOperatorChallengeHandler(
        Fallback(), root=root, arm_grace_seconds=0
    )
    context = object()
    page = SimpleNamespace(is_closed=lambda: False)
    state_dir = Path(request.handoff_state["state_dir"])
    captured = []

    async def fake_session(_request, *, state_dir, run_dir, live_session=None):
        captured.append(live_session)
        assert read_operator_status(run_dir)["state"] == "armed"
        return ChallengeResult(action="defer", message="Human still in control")

    handler._run_session = fake_session  # type: ignore[method-assign]
    register_live_operator_session(state_dir, context=context, page=page)
    try:
        result = await handler.handle(request)
    finally:
        unregister_live_operator_session(state_dir, page=page)
    assert result.action == "defer"
    assert len(captured) == 1
    assert captured[0].context is context
    assert captured[0].page is page
    assert read_operator_readiness(root)["run_id"] == request.run_id


@pytest.mark.asyncio
async def test_scheduled_run_never_claims_manually_bound_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "immowelt"
    request = _request(root)
    arm_operator_readiness(root)
    assert bind_operator_readiness("manual-only", root)
    monkeypatch.delenv(MANUAL_RUN_REQUEST_ENV, raising=False)

    class Fallback:
        calls = 0

        async def handle(self, _request):
            self.calls += 1
            return ChallengeResult(action="defer", message="unattended")

    fallback = Fallback()
    handler = ImmoweltOperatorChallengeHandler(
        fallback, root=root, arm_grace_seconds=30
    )
    context = object()
    page = SimpleNamespace(is_closed=lambda: False)
    state_dir = Path(request.handoff_state["state_dir"])
    register_live_operator_session(state_dir, context=context, page=page)
    try:
        result = await handler.handle(request)
    finally:
        unregister_live_operator_session(state_dir, page=page)
    assert result.action == "defer"
    assert fallback.calls == 1
    assert read_operator_readiness(root)["state"] == "bound"
    assert read_operator_status(operator_run_dir(123, root=root))["state"] == "idle"


def test_admin_operator_readiness_requires_admin_and_csrf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import ops

    root = tmp_path / "immowelt"
    monkeypatch.setattr(ops, "arm_operator_readiness", lambda: arm_operator_readiness(root))
    monkeypatch.setattr(ops, "clear_operator_readiness", lambda: clear_operator_readiness(root))
    monkeypatch.setattr(ops, "read_operator_readiness", lambda: read_operator_readiness(root))

    class Db:
        def get(self, _model, _id):
            return None

    def override_db():
        yield Db()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[require_csrf] = lambda: None
    try:
        with TestClient(app) as client:
            armed = client.post("/admin/health/immowelt-ready/arm", follow_redirects=False)
            assert armed.status_code == 303
            status_response = client.get("/admin/health/immowelt-ready/status")
            assert status_response.status_code == 200
            assert status_response.json()["state"] == "ready"
            assert status_response.headers["cache-control"] == "no-store"
            cleared = client.post(
                "/admin/health/immowelt-ready/clear", follow_redirects=False
            )
            assert cleared.status_code == 303
            assert client.get("/admin/health/immowelt-ready/status").json() == {
                "state": "idle"
            }
    finally:
        app.dependency_overrides.clear()
