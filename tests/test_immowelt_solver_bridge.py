from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.crawling.challenge import ChallengeRequest
from app.crawling.immowelt_solver_bridge import ImmoweltDataDomeSolverHandler


def _request(state_dir: Path, *, handoff: int = 1, datadome: bool = True) -> ChallengeRequest:
    state_dir.mkdir(parents=True, exist_ok=True)
    challenge = {
        "kind": "challenge_frame_or_redirect" if datadome else "http_403",
        "requested_url": "https://www.immowelt.de/classified-search?page=2",
        "final_url": "https://www.immowelt.de/classified-search?page=2",
        "page": 2,
    }
    if datadome:
        challenge["challenge_url"] = "https://geo.captcha-delivery.com/captcha/?id=test"
    return ChallengeRequest(
        source="immowelt-de",
        run_id=123,
        shard_id=7,
        shard_key="sachsen:030000-099999",
        shard_params={"region_key": "sachsen", "price_band_key": "030000-099999"},
        mode="incremental",
        reason="DataDome gate",
        challenge=challenge,
        resume_cursor={"_resume_same_run": True, "resume_page": 2},
        handoff_state={
            "state_dir": str(state_dir),
            "storage_state_path": str(state_dir / "storage-state.json"),
            "browser_patch_path": str(state_dir / "browser-patch.json"),
        },
        contract_version=1,
        handoff_id=f"immowelt-de:run-123:shard-7:handoff-{handoff}",
    )


@pytest.mark.asyncio
async def test_bridge_defers_unidentified_direct_403_without_calling_solver(tmp_path) -> None:
    handler = ImmoweltDataDomeSolverHandler()
    called = False

    def fail_if_called(_url: str):
        nonlocal called
        called = True
        raise AssertionError("solver must not be called")

    handler._solve = fail_if_called  # type: ignore[method-assign]

    result = await handler.handle(
        _request(tmp_path / "run-123" / "shard-7" / "handoff-1", datadome=False)
    )

    assert result.action == "defer"
    assert called is False


@pytest.mark.asyncio
async def test_bridge_stages_datadome_cookie_and_exact_user_agent(tmp_path) -> None:
    handler = ImmoweltDataDomeSolverHandler(max_candidates_per_run=2)
    handler._solve = lambda _url: {  # type: ignore[method-assign]
        "solved": True,
        "success": True,
        "datadome_cookie": "cookie-value",
        "cookie_domain": ".immowelt.de",
        "cookie_max_age": 300,
        "user_agent": "solver-exact-user-agent",
    }
    state_dir = tmp_path / "run-123" / "shard-7" / "handoff-1"

    result = await handler.handle(_request(state_dir))

    assert result.action == "resolved"
    patch = json.loads((state_dir / "browser-patch.json").read_text())
    assert patch["kind"] == "immowelt_datadome_clearance"
    assert patch["user_agent"] == "solver-exact-user-agent"
    assert patch["cookie"]["name"] == "datadome"
    assert patch["cookie"]["value"] == "cookie-value"
    run_state = json.loads((tmp_path / "run-123" / "datadome-solver-state.json").read_text())
    assert run_state["candidate_count"] == 1


@pytest.mark.asyncio
async def test_bridge_defers_repeated_clearance_candidate_instead_of_looping(tmp_path) -> None:
    handler = ImmoweltDataDomeSolverHandler(max_candidates_per_run=2)
    handler._solve = lambda _url: {  # type: ignore[method-assign]
        "solved": True,
        "success": True,
        "datadome_cookie": "same-cookie",
        "cookie_domain": ".immowelt.de",
        "cookie_max_age": 300,
        "user_agent": "same-user-agent",
    }
    first_dir = tmp_path / "run-123" / "shard-7" / "handoff-1"
    second_dir = tmp_path / "run-123" / "shard-7" / "handoff-2"

    first = await handler.handle(_request(first_dir, handoff=1))
    second = await handler.handle(_request(second_dir, handoff=2))

    assert first.action == "resolved"
    assert second.action == "defer"
    assert second.message is not None
    assert "same clearance candidate" in second.message
    assert not (second_dir / "browser-patch.json").exists()


@pytest.mark.asyncio
async def test_bridge_rejects_cookie_for_unexpected_domain(tmp_path) -> None:
    handler = ImmoweltDataDomeSolverHandler()
    handler._solve = lambda _url: {  # type: ignore[method-assign]
        "solved": True,
        "success": True,
        "datadome_cookie": "cookie-value",
        "cookie_domain": ".example.com",
        "cookie_max_age": 300,
        "user_agent": "solver-user-agent",
    }

    result = await handler.handle(
        _request(tmp_path / "run-123" / "shard-7" / "handoff-1")
    )

    assert result.action == "defer"
    assert result.message is not None
    assert "unexpected" in result.message
