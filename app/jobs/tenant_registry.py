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
    """Insert missing bootstrap tenants without overwriting later operator edits."""
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

    for seed in seeds:
        key = (seed.namespace, seed.tenant_key)
        if key in existing:
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
