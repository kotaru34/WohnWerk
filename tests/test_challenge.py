from __future__ import annotations

import sys

import pytest

from app.crawling.challenge import (
    ChallengeRequest,
    DeferredChallengeHandler,
    ExternalCommandChallengeHandler,
)


def _request() -> ChallengeRequest:
    return ChallengeRequest(
        source="immowelt-de",
        run_id=123,
        shard_id=7,
        shard_key="sachsen:030000-149999",
        shard_params={"region_key": "sachsen", "price_band_key": "030000-149999"},
        mode="incremental",
        reason="HTTP 403",
        challenge={"kind": "http_403", "page": 2},
        resume_cursor={"_resume_same_run": True, "resume_page": 2},
        handoff_state={"storage_state_path": "/tmp/state.json"},
    )


@pytest.mark.asyncio
async def test_deferred_handler_fails_closed_without_external_implementation() -> None:
    result = await DeferredChallengeHandler().handle(_request())

    assert result.action == "defer"


@pytest.mark.asyncio
async def test_external_handler_receives_json_and_returns_disposition(tmp_path) -> None:
    script = tmp_path / "handler.py"
    script.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "assert request['run_id'] == 123\n"
        "assert request['resume_cursor']['resume_page'] == 2\n"
        "json.dump({'action': 'resolved', 'retry_after_seconds': 0}, sys.stdout)\n"
    )
    handler = ExternalCommandChallengeHandler([sys.executable, str(script)], timeout_seconds=5)

    result = await handler.handle(_request())

    assert result.action == "resolved"
    assert result.retry_after_seconds == 0


@pytest.mark.asyncio
async def test_invalid_external_handler_response_defers(tmp_path) -> None:
    script = tmp_path / "handler.py"
    script.write_text("print('not-json')\n")
    handler = ExternalCommandChallengeHandler([sys.executable, str(script)], timeout_seconds=5)

    result = await handler.handle(_request())

    assert result.action == "defer"
    assert result.message is not None
    assert "invalid" in result.message
