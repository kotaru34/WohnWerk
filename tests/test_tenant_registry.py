from datetime import UTC, datetime
from types import SimpleNamespace

from app.jobs.tenant_registry import TenantSeed, mark_tenant_verified, seed_tenants
from app.models import JobSourceTenant


class _FakeSession:
    def __init__(self, rows: list[JobSourceTenant] | None = None) -> None:
        self.rows = list(rows or [])
        self.commits = 0

    def scalars(self, _statement):
        return list(self.rows)

    def add(self, row: JobSourceTenant) -> None:
        self.rows.append(row)

    def commit(self) -> None:
        self.commits += 1


def test_disabled_seed_creates_disabled_tenant() -> None:
    session = _FakeSession()
    source = SimpleNamespace(id=7)

    created = seed_tenants(
        session,
        source=source,
        seeds=[
            TenantSeed(
                tenant_key="candidate",
                company="Candidate GmbH",
                enabled=False,
                config={"candidate_evidence": "production preflight required"},
            )
        ],
    )

    assert len(created) == 1
    assert created[0].source_id == 7
    assert created[0].tenant_key == "candidate"
    assert created[0].enabled is False
    assert created[0].config == {"candidate_evidence": "production preflight required"}
    assert session.commits == 1


def test_existing_operator_enablement_is_never_overwritten_by_seed() -> None:
    existing_disabled = JobSourceTenant(
        source_id=7,
        namespace="default",
        tenant_key="disabled-by-operator",
        company="Existing GmbH",
        enabled=False,
        config={},
    )
    existing_enabled = JobSourceTenant(
        source_id=7,
        namespace="default",
        tenant_key="enabled-by-operator",
        company="Existing AG",
        enabled=True,
        config={},
    )
    session = _FakeSession([existing_disabled, existing_enabled])
    source = SimpleNamespace(id=7)

    created = seed_tenants(
        session,
        source=source,
        seeds=[
            TenantSeed(
                tenant_key="disabled-by-operator",
                company="Existing GmbH",
                enabled=True,
                config={"new_default": "kept"},
            ),
            TenantSeed(
                tenant_key="enabled-by-operator",
                company="Existing AG",
                enabled=False,
            ),
        ],
    )

    assert created == []
    assert existing_disabled.enabled is False
    assert existing_disabled.config == {"new_default": "kept"}
    assert existing_enabled.enabled is True
    assert session.commits == 1


def test_mark_tenant_verified_resolves_longest_multishard_prefix() -> None:
    workday = JobSourceTenant(
        source_id=12,
        namespace="default",
        tenant_key="magna:Magna",
        company="Magna",
        enabled=True,
        config={},
    )
    other = JobSourceTenant(
        source_id=12,
        namespace="default",
        tenant_key="other",
        company="Other",
        enabled=True,
        config={},
    )
    session = _FakeSession([workday, other])
    verified_at = datetime(2026, 8, 30, 15, 30, tzinfo=UTC)

    changed = mark_tenant_verified(
        session,
        source_id=12,
        tenant_key="magna:Magna:4",
        verified_at=verified_at,
    )

    assert changed == 1
    assert workday.last_verified_at == verified_at
    assert other.last_verified_at is None


def test_mark_tenant_verified_resolves_namespace_qualified_shard() -> None:
    lever = JobSourceTenant(
        source_id=4,
        namespace="global",
        tenant_key="tsmg",
        company="TSMG",
        enabled=True,
        config={},
    )
    other = JobSourceTenant(
        source_id=4,
        namespace="eu",
        tenant_key="tsmg-eu",
        company="Other",
        enabled=True,
        config={},
    )
    session = _FakeSession([lever, other])
    verified_at = datetime(2026, 8, 30, 16, 10, tzinfo=UTC)

    changed = mark_tenant_verified(
        session,
        source_id=4,
        tenant_key="global:tsmg",
        verified_at=verified_at,
    )

    assert changed == 1
    assert lever.last_verified_at == verified_at
    assert other.last_verified_at is None


def test_mark_tenant_verified_resolves_namespaced_multishard_prefix() -> None:
    tenant = JobSourceTenant(
        source_id=15,
        namespace="eu",
        tenant_key="example",
        company="Example",
        enabled=True,
        config={},
    )
    session = _FakeSession([tenant])
    verified_at = datetime(2026, 8, 30, 16, 12, tzinfo=UTC)

    changed = mark_tenant_verified(
        session,
        source_id=15,
        tenant_key="eu:example:2",
        verified_at=verified_at,
    )

    assert changed == 1
    assert tenant.last_verified_at == verified_at
