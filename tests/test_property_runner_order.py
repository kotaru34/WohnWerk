from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.crawling.property_runner import _ordered_shards, _source_halt_reason
from app.models import SourceShard
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
