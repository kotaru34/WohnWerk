from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Source, SourceShard
from app.sources.base import SourceShardSpec


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
