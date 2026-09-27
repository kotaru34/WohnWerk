from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Source, SourceShard
from app.sources.base import SourceShardSpec


def shard_order_matches_specs(
    run_metadata: dict | None,
    specs: list[SourceShardSpec],
) -> bool:
    """Return whether a persisted crawl shard order matches the current adapter contract."""
    persisted = dict(run_metadata or {}).get("shard_order")
    if not isinstance(persisted, list):
        return False

    persisted_keys: list[str] = []
    for item in persisted:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            return False
        persisted_keys.append(item["key"])

    current_keys = {spec.key for spec in specs}
    return len(persisted_keys) == len(current_keys) and set(persisted_keys) == current_keys


def sync_source_shards(
    session: Session,
    source: Source,
    specs: list[SourceShardSpec],
) -> list[SourceShard]:
    """Upsert deterministic adapter shards without destroying persisted cursors."""
    existing = {
        shard.key: shard
        for shard in session.scalars(select(SourceShard).where(SourceShard.source_id == source.id))
    }
    desired_keys = {spec.key for spec in specs}
    result: list[SourceShard] = []

    for spec in specs:
        shard = existing.get(spec.key)
        if shard is None:
            shard = SourceShard(source_id=source.id, key=spec.key)
            session.add(shard)
        shard.enabled = True
        shard.priority = spec.priority
        shard.params = spec.params
        shard.result_cap = spec.result_cap
        result.append(shard)

    for key, shard in existing.items():
        if key not in desired_keys:
            shard.enabled = False

    session.commit()
    return result
