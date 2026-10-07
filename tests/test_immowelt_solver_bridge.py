from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.crawling.challenge import ChallengeRequest, ExternalCommandChallengeHandler
from app.crawling.immowelt_operator_handoff import ImmoweltOperatorChallengeHandler
from app.crawling.immowelt_solver_bridge import (
    ImmoweltDataDomeSolverHandler,
    configured_immowelt_challenge_handler,
)


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
async def test_bridge_defers_interactive_bv_without_calling_silent_solver(tmp_path) -> None:
    handler = ImmoweltDataDomeSolverHandler()
    called = False

    def fail_if_called(_url: str):
        nonlocal called
        called = True
        raise AssertionError("silent solver must not be called for DataDome t=bv gates")

    handler._solve = fail_if_called  # type: ignore[method-assign]
    request = _request(tmp_path / "run-123" / "shard-7" / "handoff-1")
    request.challenge["datadome_challenge_type"] = "bv"

    result = await handler.handle(request)

    assert result.action == "defer"
    assert called is False
    assert result.message is not None
    assert "interactive verification" in result.message
    assert "harvest-only" in result.message


@pytest.mark.asyncio
async def test_bridge_defers_interactive_fe_without_calling_silent_solver(tmp_path) -> None:
    handler = ImmoweltDataDomeSolverHandler()
    called = False

    def fail_if_called(_url: str):
        nonlocal called
        called = True
        raise AssertionError("silent solver must not be called for DataDome t=fe gates")

    handler._solve = fail_if_called  # type: ignore[method-assign]
    request = _request(tmp_path / "run-123" / "shard-7" / "handoff-1")
    request.challenge["datadome_challenge_type"] = "fe"

    result = await handler.handle(request)

    assert result.action == "defer"
    assert called is False
    assert result.message is not None
    assert "interactive verification" in result.message
    assert "t=fe" in result.message
    assert "harvest-only" in result.message


@pytest.mark.asyncio
async def test_bridge_stages_datadome_cookie_and_exact_user_agent(tmp_path) -> None:
    handler = ImmoweltDataDomeSolverHandler(max_candidates_per_navigation=2)
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
    assert run_state["version"] == 1
    assert len(run_state["entries"]) == 1
    assert next(iter(run_state["entries"].values()))["candidate_count"] == 1


@pytest.mark.asyncio
async def test_bridge_defers_repeated_clearance_candidate_instead_of_looping(tmp_path) -> None:
    handler = ImmoweltDataDomeSolverHandler(max_candidates_per_navigation=2)
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


def test_runner_wraps_fail_closed_fallback_with_operator_handoff() -> None:
    handler_without_solver = configured_immowelt_challenge_handler(
        external_command=None,
        solver_url=None,
        timeout_seconds=90.0,
    )
    assert isinstance(handler_without_solver, ImmoweltOperatorChallengeHandler)

    handler = configured_immowelt_challenge_handler(
        external_command=None,
        solver_url="http://127.0.0.1:8877",
        timeout_seconds=900.0,
    )

    assert isinstance(handler, ImmoweltOperatorChallengeHandler)
    assert isinstance(handler.fallback, ImmoweltDataDomeSolverHandler)
    assert handler.fallback.solver_url == "http://127.0.0.1:8877"
    assert handler.fallback.timeout_seconds == 90.0


def test_explicit_operator_handler_keeps_precedence_over_local_solver() -> None:
    handler = configured_immowelt_challenge_handler(
        external_command="/bin/true",
        solver_url="http://127.0.0.1:8877",
        timeout_seconds=90.0,
    )

    assert isinstance(handler, ExternalCommandChallengeHandler)
    assert handler.command == ("/bin/true",)




@pytest.mark.asyncio
async def test_bridge_candidate_limit_is_scoped_to_saved_navigation(tmp_path) -> None:
    handler = ImmoweltDataDomeSolverHandler(max_candidates_per_navigation=1)
    counter = 0

    def solve(_url: str):
        nonlocal counter
        counter += 1
        return {
            "solved": True,
            "success": True,
            "datadome_cookie": f"cookie-{counter}",
            "cookie_domain": ".immowelt.de",
            "cookie_max_age": 300,
            "user_agent": "solver-user-agent",
        }

    handler._solve = solve  # type: ignore[method-assign]

    first = _request(tmp_path / "run-123" / "shard-7" / "handoff-1", handoff=1)
    same_point = _request(tmp_path / "run-123" / "shard-7" / "handoff-2", handoff=2)
    other_point = _request(tmp_path / "run-123" / "shard-7" / "handoff-3", handoff=3)
    other_point.resume_cursor["resume_page"] = 3
    other_point.challenge["requested_url"] = "https://www.immowelt.de/classified-search?page=3"

    assert (await handler.handle(first)).action == "resolved"
    assert (await handler.handle(same_point)).action == "defer"
    assert (await handler.handle(other_point)).action == "resolved"
    assert counter == 2

def test_bridge_requires_loopback_solver_base_url() -> None:
    with pytest.raises(ValueError, match="loopback"):
        ImmoweltDataDomeSolverHandler("http://solver.example.com:8877")


@pytest.mark.asyncio
async def test_bridge_rejects_proxy_backed_clearance_candidate(tmp_path) -> None:
    handler = ImmoweltDataDomeSolverHandler()
    handler._solve = lambda _url: {  # type: ignore[method-assign]
        "solved": True,
        "success": True,
        "datadome_cookie": "cookie-value",
        "cookie_domain": ".immowelt.de",
        "cookie_max_age": 300,
        "user_agent": "solver-user-agent",
        "proxy": "http://proxy.example:8080",
    }

    result = await handler.handle(
        _request(tmp_path / "run-123" / "shard-7" / "handoff-1")
    )

    assert result.action == "defer"
    assert result.message is not None
    assert "proxy" in result.message


@pytest.mark.asyncio
async def test_bridge_backfills_browser_patch_path_for_legacy_handoff(tmp_path) -> None:
    handler = ImmoweltDataDomeSolverHandler()
    handler._solve = lambda _url: {  # type: ignore[method-assign]
        "solved": True,
        "success": True,
        "datadome_cookie": "legacy-cookie",
        "cookie_domain": None,
        "cookie_max_age": 300,
        "user_agent": "legacy-user-agent",
    }
    state_dir = tmp_path / "run-123" / "shard-7" / "handoff-1"
    request = _request(state_dir)
    request.handoff_state.pop("browser_patch_path")

    result = await handler.handle(request)

    assert result.action == "resolved"
    assert request.handoff_state["browser_patch_path"] == str(
        (state_dir / "browser-patch.json").resolve()
    )
    patch = json.loads((state_dir / "browser-patch.json").read_text())
    assert patch["cookie"]["domain"] == "www.immowelt.de"
