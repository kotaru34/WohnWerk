from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.crawling.challenge import ChallengeRequest
from app.crawling.property_runner import (
    _begin_paused_challenge_revalidation,
    _complete_paused_challenge_revalidation,
    _ordered_shards,
    _prepare_paused_challenge_revalidation,
    _record_challenge_result,
    _set_active_challenge,
    _source_halt_reason,
    _tag_manual_resume,
    _touch_run_activity,
)
from app.models import CoverageStatus, SourceShard
from app.sources.base import SourceFetchError


def _shard(
    shard_id: int,
    *,
    key: str,
    last_success_at: datetime | None,
    priority: int = 100,
) -> SourceShard:
    return SourceShard(
        id=shard_id,
        source_id=1,
        key=key,
        enabled=True,
        priority=priority,
        params={},
        cursor={},
        last_success_at=last_success_at,
    )


def test_incremental_order_prefers_never_then_least_recently_successful() -> None:
    now = datetime.now(UTC)
    shards = [
        _shard(1, key="recent", last_success_at=now),
        _shard(2, key="never", last_success_at=None),
        _shard(3, key="old", last_success_at=now - timedelta(days=2)),
        _shard(4, key="middle", last_success_at=now - timedelta(hours=2)),
    ]

    ordered = _ordered_shards(shards, reconciliation=False)

    assert [item.key for item in ordered] == ["never", "old", "middle", "recent"]


def test_reconciliation_keeps_priority_then_id_order() -> None:
    now = datetime.now(UTC)
    shards = [
        _shard(9, key="nine", last_success_at=None, priority=100),
        _shard(2, key="two", last_success_at=now, priority=100),
        _shard(7, key="priority", last_success_at=now, priority=50),
    ]

    ordered = _ordered_shards(shards, reconciliation=True)

    assert [item.key for item in ordered] == ["priority", "two", "nine"]


def test_source_halt_reason_only_accepts_explicit_halt_signal() -> None:
    normal = SourceFetchError("temporary shard failure")
    halted = SourceFetchError("source gate", halt_source=True)

    assert _source_halt_reason(normal) is None
    assert _source_halt_reason(halted) == "source gate"
    assert _source_halt_reason(RuntimeError("other")) is None



def test_manual_resume_tags_existing_run_without_losing_metadata() -> None:
    run = SimpleNamespace(run_metadata={"shard_order": [{"id": 1}]})

    _tag_manual_resume(run, "manual-request-123")

    assert run.run_metadata["shard_order"] == [{"id": 1}]
    assert run.run_metadata["manual_run_request_id"] == "manual-request-123"
    assert run.run_metadata["manual_resume_requested_at"]
    assert run.run_metadata["last_activity_at"]


def test_run_activity_touch_preserves_existing_metadata() -> None:
    run = SimpleNamespace(run_metadata={"shard_order": [{"id": 1}]})

    _touch_run_activity(run, at=datetime(2026, 10, 4, 20, 15, tzinfo=UTC))

    assert run.run_metadata["shard_order"] == [{"id": 1}]
    assert run.run_metadata["last_activity_at"] == "2026-10-04T20:15:00+00:00"


def test_paused_resume_revalidation_preserves_checkpoint_until_success() -> None:
    request = ChallengeRequest(
        source="immowelt-de",
        run_id=77,
        shard_id=9,
        shard_key="sachsen:030000-099999",
        shard_params={"region_key": "sachsen"},
        mode="incremental",
        reason="stale DataDome challenge",
        challenge={"kind": "http_403", "datadome_challenge_type": "bv"},
        resume_cursor={"_resume_same_run": True, "resume_page": 1},
        handoff_state={"state_dir": "/tmp/stale-handoff"},
        handoff_id="immowelt-de:run-77:shard-9:handoff-1",
    )
    run = SimpleNamespace(
        run_metadata={"active_challenge": request.to_payload(), "challenge_handoff_count": 1},
        status="paused",
        coverage_status=CoverageStatus.DEGRADED,
    )
    cursor = _begin_paused_challenge_revalidation(run, request)

    assert cursor == {"_resume_same_run": True, "resume_page": 1}
    assert run.run_metadata["active_challenge"] == request.to_payload()
    assert run.run_metadata["challenge_handoff_count"] == 1
    assert run.run_metadata["challenge_history"][-1]["action"] == "revalidate"
    assert run.status == "paused"
    assert run.coverage_status == CoverageStatus.DEGRADED

    _record_challenge_result(
        run,
        request,
        action="resolved",
        message="challenge absent on resume revalidation",
    )
    assert "active_challenge" not in run.run_metadata


def test_persistent_revalidation_replaces_checkpoint_and_stays_fail_closed() -> None:
    request = ChallengeRequest(
        source="immoscout24-de",
        run_id=88,
        shard_id=10,
        shard_key="sachsen:030000-099999",
        shard_params={"region_key": "sachsen"},
        mode="incremental",
        reason="old verification",
        challenge={"kind": "challenge_content"},
        resume_cursor={"_resume_same_run": True, "resume_page": 1},
        handoff_state={"state_dir": "/tmp/old-handoff"},
        handoff_id="immoscout24-de:run-88:shard-10:handoff-1",
    )
    run = SimpleNamespace(
        run_metadata={"active_challenge": request.to_payload(), "challenge_handoff_count": 1}
    )
    _begin_paused_challenge_revalidation(run, request)
    _record_challenge_result(
        run,
        request,
        action="defer",
        message="challenge still present on resume revalidation",
    )
    replacement = ChallengeRequest(
        source=request.source,
        run_id=request.run_id,
        shard_id=request.shard_id,
        shard_key=request.shard_key,
        shard_params=request.shard_params,
        mode=request.mode,
        reason="fresh verification",
        challenge={"kind": "challenge_content", "http_status": 401},
        resume_cursor=request.resume_cursor,
        handoff_state={"state_dir": "/tmp/new-handoff"},
        handoff_id="immoscout24-de:run-88:shard-10:handoff-2",
    )
    _set_active_challenge(run, replacement, handoff_count=2)

    assert run.run_metadata["active_challenge"] == replacement.to_payload()
    assert run.run_metadata["challenge_handoff_count"] == 2
    assert run.run_metadata["challenge_history"][-1]["action"] == "defer"


@pytest.mark.asyncio
async def test_paused_resume_restores_browser_state_before_revalidation() -> None:
    restored: list[dict] = []

    class Adapter:
        async def restore_challenge_handoff(self, handoff_state: dict) -> None:
            restored.append(dict(handoff_state))

    request = ChallengeRequest(
        source="immowelt-de",
        run_id=77,
        shard_id=9,
        shard_key="sachsen:030000-099999",
        shard_params={"region_key": "sachsen"},
        mode="incremental",
        reason="persisted DataDome challenge",
        challenge={"kind": "http_403", "datadome_challenge_type": "fe"},
        resume_cursor={"_resume_same_run": True, "resume_page": 2},
        handoff_state={
            "state_dir": "/tmp/persisted-handoff",
            "storage_state_path": "/tmp/persisted-handoff/storage-state.json",
            "user_agent": "persisted-exact-ua",
            "viewport": {"width": 1280, "height": 720},
        },
        handoff_id="immowelt-de:run-77:shard-9:handoff-1",
    )
    run = SimpleNamespace(
        run_metadata={"active_challenge": request.to_payload(), "challenge_handoff_count": 1},
        status="paused",
        coverage_status=CoverageStatus.DEGRADED,
    )

    cursor = await _prepare_paused_challenge_revalidation(
        Adapter(),  # type: ignore[arg-type]
        run,
        request,
    )

    assert restored == [request.handoff_state]
    assert cursor["resume_page"] == 2
    assert run.run_metadata["challenge_history"][-1]["action"] == "revalidate"


def test_successful_paused_revalidation_marks_run_running_before_clearing_checkpoint() -> None:
    request = ChallengeRequest(
        source="immowelt-de",
        run_id=5854,
        shard_id=9,
        shard_key="sachsen:030000-099999",
        shard_params={"region_key": "sachsen"},
        mode="incremental",
        reason="fresh DataDome verification",
        challenge={"kind": "http_403", "datadome_challenge_type": "fe"},
        resume_cursor={"_resume_same_run": True, "resume_page": 1},
        handoff_state={"state_dir": "/tmp/run-5854/handoff-1"},
        handoff_id="immowelt-de:run-5854:shard-9:handoff-1",
    )
    run = SimpleNamespace(
        run_metadata={"active_challenge": request.to_payload()},
        status="paused",
        coverage_status=CoverageStatus.DEGRADED,
    )

    _complete_paused_challenge_revalidation(run, request)

    assert run.status == "running"
    assert run.coverage_status == CoverageStatus.UNKNOWN
    assert "active_challenge" not in run.run_metadata
    assert run.run_metadata["challenge_history"][-1]["action"] == "resolved"
