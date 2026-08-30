from pathlib import Path
from runpy import run_path

import pytest

from app.sources.base import RawJob, RawJobLocation, SourceBatch

_SCRIPT = run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "run_lever_jobs.py"))
DEFAULT_TENANTS = _SCRIPT["DEFAULT_TENANTS"]
LeverJobSource = _SCRIPT["LeverJobSource"]
_bootstrap_sites = _SCRIPT["_bootstrap_sites"]
_curated_tenant_states = _SCRIPT["_curated_tenant_states"]
preflight_sites = _SCRIPT["preflight_sites"]


def _job(title: str, description: str) -> RawJob:
    return RawJob(
        source_listing_id=title,
        url="https://example.invalid/lever/job",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Graz", location_text="Graz, Austria")],
    )


def test_bootstrap_sites_preserve_region_and_company() -> None:
    sites = _bootstrap_sites()

    assert [(site.region, site.site, site.company) for site in sites] == [
        ("eu", "blackshark", "Blackshark.ai"),
        ("eu", "westernacher", "Westernacher Consulting"),
        ("global", "cargo-partner", "cargo-partner"),
        ("global", "qualysoft", "Qualysoft"),
        ("global", "tsmg", "TSMG"),
    ]


def test_curated_bootstrap_defaults_only_enable_tsmg() -> None:
    assert {
        (seed.namespace, seed.tenant_key): seed.enabled for seed in DEFAULT_TENANTS
    } == {
        ("eu", "blackshark"): False,
        ("eu", "westernacher"): False,
        ("global", "cargo-partner"): False,
        ("global", "qualysoft"): False,
        ("global", "tsmg"): True,
    }

    assert _curated_tenant_states() == {
        ("eu", "blackshark"): False,
        ("eu", "westernacher"): False,
        ("global", "cargo-partner"): False,
        ("global", "qualysoft"): False,
        ("global", "tsmg"): True,
    }


@pytest.mark.asyncio
async def test_preflight_classifies_every_bootstrap_site_without_database(monkeypatch, capsys) -> None:
    async def fake_fetch_shard(self, shard, *, cursor=None, reconciliation=False):
        del self, shard, cursor
        assert reconciliation is True
        return SourceBatch(
            items=[
                _job(
                    "Mechanical Design Engineer",
                    "Mechanical product development, CAD, FMEA and validation.",
                ),
                _job(
                    "Backend Engineer",
                    "Software, Kubernetes and cloud infrastructure.",
                ),
            ],
            source_reported_count=2,
            coverage_complete=True,
            result_cap_hit=False,
            pages_fetched=1,
        )

    monkeypatch.setattr(LeverJobSource, "fetch_shard", fake_fetch_shard)

    ok = await preflight_sites(
        page_size=100,
        hard_max_pages=10,
        delay=0,
    )

    output = capsys.readouterr().out
    assert ok is True
    assert output.count("=ok ") == 5
    assert output.count("accepted=1 rejected=1") == 5
    assert "accepted=Mechanical Design Engineer" in output
    assert "lever_preflight=success" in output


@pytest.mark.asyncio
async def test_preflight_fails_closed_on_incomplete_tenant(monkeypatch, capsys) -> None:
    async def fake_fetch_shard(self, shard, *, cursor=None, reconciliation=False):
        del self, shard, cursor
        assert reconciliation is True
        return SourceBatch(
            items=[],
            coverage_complete=False,
            result_cap_hit=True,
            pages_fetched=3,
        )

    monkeypatch.setattr(LeverJobSource, "fetch_shard", fake_fetch_shard)

    ok = await preflight_sites(
        page_size=100,
        hard_max_pages=3,
        delay=0,
    )

    output = capsys.readouterr().out
    assert ok is False
    assert output.count("=failed error=incomplete_coverage") == 5
    assert "lever_preflight=failed" in output
