from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.crawling.immowelt_operator_handoff as operator_module
from app.crawling.challenge import ChallengeRequest, ChallengeResult
from app.crawling.immowelt_operator_handoff import (
    ImmoweltOperatorChallengeHandler,
    _has_immowelt_datadome_cookie,
    arm_operator_handoff,
    enqueue_operator_pointer,
    operator_approval_path,
    operator_events_path,
    prepare_fresh_operator_reverification,
    read_operator_status,
    register_live_operator_session,
    unregister_live_operator_session,
)


class _Fallback:
    def __init__(self) -> None:
        self.calls = 0

    async def handle(self, request: ChallengeRequest) -> ChallengeResult:
        self.calls += 1
        return ChallengeResult(action="defer", message=f"fallback:{request.run_id}")


def _request(root: Path, *, challenge_type: str = "fe") -> ChallengeRequest:
    state_dir = root / "run-123" / "shard-7" / "handoff-2"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "storage-state.json").write_text('{"cookies":[],"origins":[]}\n')
    return ChallengeRequest(
        source="immowelt-de",
        run_id=123,
        shard_id=7,
        shard_key="baden-wuerttemberg:150000-200000",
        shard_params={},
        mode="incremental",
        reason="DataDome gate",
        challenge={
            "kind": "http_403",
            "requested_url": "https://www.immowelt.de/classified-search?page=2",
            "datadome_challenge_type": challenge_type,
        },
        resume_cursor={"resume_page": 2},
        handoff_state={
            "state_dir": str(state_dir),
            "storage_state_path": str(state_dir / "storage-state.json"),
        },
        handoff_id="immowelt-de:run-123:shard-7:handoff-2",
    )


def _active_payload(request: ChallengeRequest) -> dict:
    return request.to_payload()


@pytest.mark.asyncio
async def test_clearance_requires_immowelt_datadome_cookie() -> None:
    class _Context:
        def __init__(self, cookies):
            self._cookies = cookies

        async def cookies(self):
            return self._cookies

    assert await _has_immowelt_datadome_cookie(
        _Context([{"name": "datadome", "value": "ok", "domain": ".immowelt.de"}])
    )
    assert not await _has_immowelt_datadome_cookie(
        _Context([{"name": "datadome", "value": "ok", "domain": ".example.com"}])
    )
    assert not await _has_immowelt_datadome_cookie(
        _Context([{"name": "other", "value": "ok", "domain": ".immowelt.de"}])
    )


def test_arm_operator_handoff_is_explicit_and_run_scoped(tmp_path: Path) -> None:
    request = _request(tmp_path)
    run_dir = arm_operator_handoff(
        request.run_id,
        _active_payload(request),
        root=tmp_path,
        now=datetime(2026, 10, 7, 3, 0, tzinfo=UTC),
    )

    approval = json.loads(operator_approval_path(run_dir).read_text())
    assert approval["version"] == 1
    assert approval["run_id"] == 123
    assert approval["armed_at"] == "2026-10-07T03:00:00+00:00"
    assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700
    assert read_operator_status(
        run_dir,
        now=datetime(2026, 10, 7, 3, 1, tzinfo=UTC),
    )["state"] == "armed"


def test_pointer_events_store_only_operator_input(tmp_path: Path) -> None:
    request = _request(tmp_path)
    run_dir = arm_operator_handoff(request.run_id, _active_payload(request), root=tmp_path)

    enqueue_operator_pointer(run_dir, phase="down", x=0.2, y=0.7)
    enqueue_operator_pointer(run_dir, phase="move", x=0.6, y=0.7)
    enqueue_operator_pointer(run_dir, phase="up", x=0.8, y=0.7)

    rows = [
        json.loads(line)
        for line in operator_events_path(run_dir).read_text().splitlines()
    ]
    assert [row["phase"] for row in rows] == ["down", "move", "up"]
    assert rows[0]["x"] == 0.2
    assert rows[-1]["x"] == 0.8


def test_arm_rejects_noninteractive_challenge(tmp_path: Path) -> None:
    request = _request(tmp_path, challenge_type="")

    with pytest.raises(ValueError, match="not an interactive"):
        arm_operator_handoff(request.run_id, _active_payload(request), root=tmp_path)


@pytest.mark.asyncio
async def test_unarmed_interactive_challenge_keeps_fail_closed_fallback(tmp_path: Path) -> None:
    fallback = _Fallback()
    handler = ImmoweltOperatorChallengeHandler(fallback, root=tmp_path)
    request = _request(tmp_path)

    result = await handler.handle(request)

    assert result.action == "defer"
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_armed_interactive_challenge_uses_operator_session(tmp_path: Path) -> None:
    fallback = _Fallback()
    handler = ImmoweltOperatorChallengeHandler(fallback, root=tmp_path)
    request = _request(tmp_path)
    arm_operator_handoff(request.run_id, _active_payload(request), root=tmp_path)

    calls = []

    async def fake_session(_request, *, state_dir, run_dir, live_session=None):
        calls.append((state_dir, run_dir, live_session))
        return ChallengeResult(action="resolved", message="human completed")

    handler._run_session = fake_session  # type: ignore[method-assign]

    result = await handler.handle(request)

    assert result.action == "resolved"
    assert fallback.calls == 0
    assert len(calls) == 1
    assert calls[0][1] == tmp_path / "run-123"
    assert calls[0][2] is None


class _TimeoutPage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.frames = []

    async def goto(self, url: str, **_kwargs: object) -> None:
        self.url = url

    async def close(self) -> None:
        return None


class _TimeoutContext:
    def __init__(self) -> None:
        self.page = _TimeoutPage()

    async def new_page(self) -> _TimeoutPage:
        return self.page

    async def close(self) -> None:
        return None


class _TimeoutBrowser:
    def __init__(self) -> None:
        self.context = _TimeoutContext()

    async def new_context(self, **_kwargs: object) -> _TimeoutContext:
        return self.context

    async def close(self) -> None:
        return None


class _TimeoutChromium:
    def __init__(self) -> None:
        self.browser = _TimeoutBrowser()

    async def launch(self, **_kwargs: object) -> _TimeoutBrowser:
        return self.browser


class _TimeoutPlaywright:
    def __init__(self) -> None:
        self.chromium = _TimeoutChromium()

    async def stop(self) -> None:
        return None


class _TimeoutStarter:
    def __init__(self, playwright: _TimeoutPlaywright) -> None:
        self.playwright = playwright

    async def start(self) -> _TimeoutPlaywright:
        return self.playwright


@pytest.mark.asyncio
async def test_operator_session_timeout_defers_without_clearance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    state_dir = Path(str(request.handoff_state["state_dir"]))
    run_dir = tmp_path / "run-123"
    fake = _TimeoutPlaywright()
    ticks = iter((0.0, 100.0))

    monkeypatch.setattr(operator_module, "async_playwright", lambda: _TimeoutStarter(fake))
    monkeypatch.setattr(
        operator_module,
        "time",
        SimpleNamespace(monotonic=lambda: next(ticks)),
    )

    handler = ImmoweltOperatorChallengeHandler(
        _Fallback(),
        root=tmp_path,
        timeout_seconds=30,
    )
    result = await handler._run_session(
        request,
        state_dir=state_dir,
        run_dir=run_dir,
    )

    assert result.action == "defer"
    assert result.message == "operator handoff timed out without completed verification"
    assert read_operator_status(run_dir)["state"] == "timeout"


@pytest.mark.asyncio
async def test_armed_interactive_challenge_reuses_registered_live_browser(tmp_path: Path) -> None:
    fallback = _Fallback()
    handler = ImmoweltOperatorChallengeHandler(fallback, root=tmp_path)
    request = _request(tmp_path)
    state_dir = Path(str(request.handoff_state["state_dir"]))
    arm_operator_handoff(request.run_id, _active_payload(request), root=tmp_path)

    context = object()

    class Page:
        def is_closed(self) -> bool:
            return False

    page = Page()
    register_live_operator_session(state_dir, context=context, page=page)
    captured = []

    async def fake_session(_request, *, state_dir, run_dir, live_session=None):
        captured.append(live_session)
        return ChallengeResult(action="resolved", message="same browser")

    handler._run_session = fake_session  # type: ignore[method-assign]
    try:
        result = await handler.handle(request)
    finally:
        unregister_live_operator_session(state_dir, page=page)

    assert result.action == "resolved"
    assert fallback.calls == 0
    assert len(captured) == 1
    assert captured[0] is not None
    assert captured[0].context is context
    assert captured[0].page is page


@pytest.mark.asyncio
async def test_live_browser_waits_for_explicit_operator_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # The legacy 120s grace now only applies to an explicitly manual run.
    monkeypatch.setenv("WOHNWERK_MANUAL_RUN_REQUEST_ID", "human-manual-run")
    fallback = _Fallback()
    handler = ImmoweltOperatorChallengeHandler(
        fallback,
        root=tmp_path,
        arm_grace_seconds=30,
    )
    request = _request(tmp_path)
    state_dir = Path(str(request.handoff_state["state_dir"]))
    context = object()

    class Page:
        def is_closed(self) -> bool:
            return False

    page = Page()
    register_live_operator_session(state_dir, context=context, page=page)
    approval_checks = iter((False, True))
    monkeypatch.setattr(
        operator_module,
        "_approval_is_active",
        lambda *_args, **_kwargs: next(approval_checks),
    )
    captured = []

    async def fake_session(_request, *, state_dir, run_dir, live_session=None):
        captured.append(live_session)
        return ChallengeResult(action="resolved", message="approved live session")

    handler._run_session = fake_session  # type: ignore[method-assign]
    try:
        result = await handler.handle(request)
    finally:
        unregister_live_operator_session(state_dir, page=page)

    assert result.action == "resolved"
    assert fallback.calls == 0
    assert len(captured) == 1
    assert captured[0] is not None
    assert captured[0].context is context
    assert captured[0].page is page


def test_fresh_reverification_strips_only_immowelt_datadome_cookie(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    storage = Path(str(request.handoff_state["storage_state_path"]))
    storage.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "datadome",
                        "value": "stale-clearance",
                        "domain": ".immowelt.de",
                        "path": "/",
                    },
                    {
                        "name": "datadome",
                        "value": "unrelated",
                        "domain": ".example.com",
                        "path": "/",
                    },
                    {
                        "name": "session",
                        "value": "keep-me",
                        "domain": ".immowelt.de",
                        "path": "/",
                    },
                ],
                "origins": [
                    {
                        "origin": "https://www.immowelt.de",
                        "localStorage": [{"name": "keep", "value": "state"}],
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    removed = prepare_fresh_operator_reverification(
        request.run_id,
        _active_payload(request),
        root=tmp_path,
    )

    state = json.loads(storage.read_text(encoding="utf-8"))
    assert removed == 1
    assert [(item["name"], item["domain"]) for item in state["cookies"]] == [
        ("datadome", ".example.com"),
        ("session", ".immowelt.de"),
    ]
    assert state["origins"][0]["localStorage"] == [{"name": "keep", "value": "state"}]
    assert stat.S_IMODE(storage.stat().st_mode) == 0o600
