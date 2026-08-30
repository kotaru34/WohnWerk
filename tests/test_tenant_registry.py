from types import SimpleNamespace

from app.jobs.tenant_registry import TenantSeed, seed_tenants
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
