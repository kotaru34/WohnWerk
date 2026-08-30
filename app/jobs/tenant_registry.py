from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import JobSourceTenant, Source


@dataclass(frozen=True, slots=True)
class TenantSeed:
    tenant_key: str
    company: str
    namespace: str = "default"
    config: dict = field(default_factory=dict)
    enabled: bool = True


def seed_tenants(
    session: Session,
    *,
    source: Source,
    seeds: list[TenantSeed],
) -> list[JobSourceTenant]:
    """Insert bootstrap tenants and add only missing config defaults.

    Existing operator values are never overwritten. This lets adapters introduce a
    new source-specific default for an already discovered tenant without resetting
    manual enable/disable state or explicit configuration. The seed ``enabled``
    value is therefore used only when a tenant row is first created.
    """
    if not seeds:
        return []

    existing = {
        (row.namespace, row.tenant_key): row
        for row in session.scalars(
            select(JobSourceTenant).where(JobSourceTenant.source_id == source.id)
        )
    }
    now = datetime.now(UTC)
    created: list[JobSourceTenant] = []
    changed = False

    for seed in seeds:
        key = (seed.namespace, seed.tenant_key)
        row = existing.get(key)
        if row is not None:
            merged_config = dict(row.config or {})
            before = dict(merged_config)
            for config_key, value in seed.config.items():
                merged_config.setdefault(config_key, value)
            if merged_config != before:
                row.config = merged_config
                changed = True
            continue

        row = JobSourceTenant(
            source_id=source.id,
            namespace=seed.namespace,
            tenant_key=seed.tenant_key,
            company=seed.company,
            enabled=seed.enabled,
            config=dict(seed.config),
            discovered_at=now,
        )
        session.add(row)
        created.append(row)
        existing[key] = row
        changed = True

    if changed:
        session.commit()
    return created


def enabled_tenants(session: Session, *, source: Source) -> list[JobSourceTenant]:
    return list(
        session.scalars(
            select(JobSourceTenant)
            .where(
                JobSourceTenant.source_id == source.id,
                JobSourceTenant.enabled.is_(True),
            )
            .order_by(JobSourceTenant.namespace, JobSourceTenant.tenant_key)
        )
    )


def _tenant_key_candidates(row: JobSourceTenant) -> tuple[str, ...]:
    qualified = (
        f"{row.namespace}:{row.tenant_key}"
        if row.namespace and row.namespace != "default"
        else row.tenant_key
    )
    if qualified == row.tenant_key:
        return (row.tenant_key,)
    return (qualified, row.tenant_key)


def mark_tenant_verified(
    session: Session,
    *,
    source_id: int,
    tenant_key: str,
    verified_at: datetime,
) -> int:
    """Record a successful source-level tenant check without committing the session.

    Shards may use the bare tenant key, a namespace-qualified key such as
    ``global:tsmg``, or a multi-frontier suffix such as ``magna:Magna:4``.
    Resolve the most specific unique enabled registry key instead of leaving
    ``last_verified_at`` empty for otherwise healthy tenant-backed sources.
    """
    enabled = list(
        session.scalars(
            select(JobSourceTenant).where(
                JobSourceTenant.source_id == source_id,
                JobSourceTenant.enabled.is_(True),
            )
        )
    )

    exact = [
        row
        for row in enabled
        if tenant_key in _tenant_key_candidates(row)
    ]
    if len(exact) == 1:
        rows = exact
    elif exact:
        rows = []
    else:
        prefix_matches: list[tuple[int, JobSourceTenant]] = []
        for row in enabled:
            for candidate in _tenant_key_candidates(row):
                if tenant_key.startswith(f"{candidate}:"):
                    prefix_matches.append((len(candidate), row))

        if not prefix_matches:
            rows = []
        else:
            longest = max(length for length, _row in prefix_matches)
            most_specific = [
                row
                for length, row in prefix_matches
                if length == longest
            ]
            unique = {id(row): row for row in most_specific}
            rows = list(unique.values()) if len(unique) == 1 else []

    for row in rows:
        row.last_verified_at = verified_at
    return len(rows)
