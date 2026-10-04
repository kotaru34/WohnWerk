from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.crawling.challenge import ChallengeRequest
from app.crawling.property_runner import (
    _begin_manual_challenge_revalidation,
    _ordered_shards,
    _source_halt_reason,
    _tag_manual_resume,
)
from app.models import CoverageStatus, RunStatus, SourceShard
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


def test_manual_resume_revalidates_stale_challenge_before_handler() -> None:
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
    shard_run = SimpleNamespace(
        status="paused",
        finished_at=datetime.now(UTC),
        error="old challenge",
    )

    cursor = _begin_manual_challenge_revalidation(run, shard_run, request)

    assert cursor == {"_resume_same_run": True, "resume_page": 1}
    assert "active_challenge" not in run.run_metadata
    assert run.run_metadata["challenge_handoff_count"] == 1
    assert run.run_metadata["challenge_history"][-1]["action"] == "revalidate"
    assert run.status == RunStatus.RUNNING
    assert run.coverage_status == CoverageStatus.UNKNOWN
    assert shard_run.status == RunStatus.RUNNING
    assert shard_run.finished_at is None
    assert shard_run.error is None
