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


def seed_tenants(
    session: Session,
    *,
    source: Source,
    seeds: list[TenantSeed],
) -> list[JobSourceTenant]:
    """Insert bootstrap tenants and add only missing config defaults.

    Existing operator values are never overwritten. This lets adapters introduce a
    new source-specific default for an already discovered tenant without resetting
    manual enable/disable state or explicit configuration.
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
            enabled=True,
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
