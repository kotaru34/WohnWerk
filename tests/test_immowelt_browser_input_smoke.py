"""Offline end-to-end headed Chromium pointer delivery smoke.

Runs only when WOHNWERK_BROWSER_SMOKE=1 and Chromium/Xvfb are installed.
No external URLs, CAPTCHA service, provider cookies or credentials are used.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.async_api import async_playwright

from app.crawling.challenge import ChallengeRequest, ChallengeResult
from app.crawling.immowelt_operator_handoff import (
    ImmoweltOperatorChallengeHandler,
    enqueue_operator_pointer,
    read_operator_status,
)


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("WOHNWERK_BROWSER_SMOKE") != "1",
    reason="Opt-in local headed Chromium smoke only",
)
async def test_real_headed_chromium_receives_human_queue_stroke(tmp_path: Path) -> None:
    """Validate actual CDP mouse delivery to a local synthetic drag surface."""
    state_dir = tmp_path / "run-321" / "shard-1" / "handoff-1"
    state_dir.mkdir(parents=True)
    run_dir = tmp_path / "run-321"
    request = ChallengeRequest(
        source="immowelt-de",
        run_id=321,
        shard_id=1,
        shard_key="test-shard",
        shard_params={},
        mode="incremental",
        reason="local simulated challenge",
        challenge={
            "kind": "local_test",
            "requested_url": "https://www.immowelt.de/classified-search?page=1",
            "datadome_challenge_type": "fe",
        },
        resume_cursor={"resume_page": 1},
        handoff_state={
            "state_dir": str(state_dir),
            "storage_state_path": str(state_dir / "storage-state.json"),
            "viewport": {"width": 1280, "height": 720},
        },
        handoff_id="local-test-handoff",
    )

    class NoFallback:
        async def handle(self, _request: ChallengeRequest) -> ChallengeResult:
            raise AssertionError("Live session must not invoke fallback")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        try:
            context = await browser.new_context(viewport={"width": 1280, "height": 720})
            page = await context.new_page()
            await page.set_content(
                """
                <!doctype html>
                <meta charset="utf-8">
                <style>body { margin: 0; } #drag { position:fixed;
                inset:0; background:#eee; touch-action:none; }</style>
                <div id="drag">Local pointer test – provider access denied</div>
                <script>
                window.inputEvents = [];
                for (const kind of ["pointerdown","pointermove","pointerup"]) {
                  document.addEventListener(kind, e => {
                    window.inputEvents.push({
                      type: kind, x: Math.round(e.clientX),
                      y: Math.round(e.clientY)
                    });
                  });
                }
                </script>
                Der Zugriff ist vorübergehend eingeschränkt
                """
            )
            enqueue_operator_pointer(run_dir, phase="down", x=0.1, y=0.2)
            enqueue_operator_pointer(run_dir, phase="move", x=0.5, y=0.2)
            enqueue_operator_pointer(run_dir, phase="up", x=0.8, y=0.2)
            handler = ImmoweltOperatorChallengeHandler(NoFallback(), root=tmp_path)
            result = await handler._run_session(
                request, state_dir=state_dir, run_dir=run_dir,
                live_session=SimpleNamespace(context=context, page=page),
            )

            assert result.action == "defer"
            status = read_operator_status(run_dir)
            assert status["state"] == "blocked"
            assert status["pointer_sequence_completed"] is True
            assert status["pointer_down_events"] == 1
            assert status["pointer_up_events"] == 1
            events = await page.evaluate("window.inputEvents")
            downs = [e for e in events if e["type"] == "pointerdown"]
            ups = [e for e in events if e["type"] == "pointerup"]
            moves = [e for e in events if e["type"] == "pointermove"]
            assert downs == [{"type": "pointerdown", "x": 128, "y": 144}]
            assert ups == [{"type": "pointerup", "x": 1024, "y": 144}]
            assert any(e["x"] == 640 and e["y"] == 144 for e in moves)
            assert events.index(downs[0]) < events.index(ups[0])
        finally:
            await browser.close()
