"""Local-only headed-browser smoke for the v0.4.29 original-live handoff.

Requires a real Playwright Chromium + DISPLAY/Xvfb. Intentionally never
navigates Immowelt, solves a challenge or reads production browser state.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

from app.crawling.challenge import ChallengeRequest, ChallengeResult
from app.crawling.immowelt_operator_handoff import (
    ImmoweltOperatorChallengeHandler,
    read_operator_status,
    register_live_operator_session,
    unregister_live_operator_session,
)
from app.crawling.immowelt_operator_ready import (
    arm_operator_readiness,
    bind_operator_readiness,
    consume_operator_readiness,
    read_operator_readiness,
)
from app.refresh import MANUAL_RUN_REQUEST_ENV


async def smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="immowelt-local-live-smoke-") as directory:
        root = Path(directory)
        state_dir = root / "run-123" / "shard-1" / "handoff-1"
        state_dir.mkdir(parents=True)
        arm_operator_readiness(root)
        assert bind_operator_readiness("local-smoke", root)
        os.environ[MANUAL_RUN_REQUEST_ENV] = "local-smoke"

        request = ChallengeRequest(
            source="immowelt-de",
            run_id=123,
            shard_id=1,
            shard_key="local-only",
            shard_params={},
            mode="incremental",
            reason="local-only fixture",
            challenge={
                "datadome_challenge_type": "fe",
                # Validated but NEVER requested: _run_session is replaced below.
                "requested_url": "https://www.immowelt.de/classified-search?page=1",
            },
            resume_cursor={},
            handoff_state={"state_dir": str(state_dir)},
        )

        class FailClosed:
            async def handle(self, _request: ChallengeRequest) -> ChallengeResult:
                raise AssertionError("unexpected fallback or new browser")

        handler = ImmoweltOperatorChallengeHandler(
            FailClosed(), root=root, arm_grace_seconds=0
        )

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=False)
            try:
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto("data:text/html,<h1>Local human fixture</h1>")
                assert await page.locator("h1").inner_text() == "Local human fixture"
                register_live_operator_session(state_dir, context=context, page=page)
                calls = []

                async def verify_handoff(
                    _request: ChallengeRequest, *, state_dir: Path,
                    run_dir: Path, live_session=None,
                ) -> ChallengeResult:
                    assert live_session is not None
                    assert live_session.context is context
                    assert live_session.page is page
                    assert read_operator_status(run_dir)["state"] == "armed"
                    assert read_operator_readiness(root)["run_id"] == 123
                    calls.append(live_session)
                    return ChallengeResult(action="defer", message="local-only smoke")

                handler._run_session = verify_handoff  # type: ignore[method-assign]
                result = await handler.handle(request)
                assert result.action == "defer"
                assert len(calls) == 1
                assert not consume_operator_readiness(123, root, request_id="local-smoke")
                print("LIVE_OPERATOR_SMOKE_OK original_context=1 original_page=1 requests_to_provider=0")
            finally:
                unregister_live_operator_session(state_dir)
                await browser.close()


if __name__ == "__main__":
    asyncio.run(smoke())
