import pytest

from app.sources.base import RawJob, RawJobLocation, SourceBatch
from scripts import run_lever_jobs


def _job(title: str, description: str) -> RawJob:
    return RawJob(
        source_listing_id=title,
        url="https://example.invalid/lever/job",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Graz", location_text="Graz, Austria")],
    )


def test_bootstrap_sites_preserve_region_and_company() -> None:
    sites = run_lever_jobs._bootstrap_sites()

    assert [(site.region, site.site, site.company) for site in sites] == [
        ("eu", "blackshark", "Blackshark.ai"),
        ("eu", "westernacher", "Westernacher Consulting"),
        ("global", "cargo-partner", "cargo-partner"),
        ("global", "qualysoft", "Qualysoft"),
        ("global", "tsmg", "TSMG"),
    ]


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

    monkeypatch.setattr(run_lever_jobs.LeverJobSource, "fetch_shard", fake_fetch_shard)

    ok = await run_lever_jobs.preflight_sites(
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

    monkeypatch.setattr(run_lever_jobs.LeverJobSource, "fetch_shard", fake_fetch_shard)

    ok = await run_lever_jobs.preflight_sites(
        page_size=100,
        hard_max_pages=3,
        delay=0,
    )

    output = capsys.readouterr().out
    assert ok is False
    assert output.count("=failed error=incomplete_coverage") == 5
    assert "lever_preflight=failed" in output
