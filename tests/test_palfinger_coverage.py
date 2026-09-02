import pytest

from app.sources.job.palfinger import PalfingerJobSource


@pytest.mark.asyncio
async def test_palfinger_listing_detail_404_makes_coverage_incomplete(monkeypatch) -> None:
    adapter = PalfingerJobSource(request_delay_seconds=0)
    listing_html = """
    <html><body>
      <a href="/worldwide/en/career/jobs/experienced-mechanical-engineer--f-m-d-_9001.html">
        Experienced Mechanical Engineer
      </a>
      <a href="/worldwide/en/career/jobs.html?area=&amp;city=&amp;country=austria&amp;page=1">1</a>
    </body></html>
    """

    async def fake_request_text(client, url: str) -> tuple[int, str]:
        del client
        if "jobs.html" in url:
            return 200, listing_html
        return 404, ""

    monkeypatch.setattr(adapter, "_request_text", fake_request_text)

    batch = await adapter.fetch_shard(
        adapter.default_shards()[0],
        reconciliation=True,
    )

    assert batch.source_reported_count == 1
    assert batch.items == []
    assert batch.coverage_complete is False
    assert batch.result_cap_hit is False
    assert batch.next_cursor["listing_pages_fetched"] == 1
    assert batch.next_cursor["listing_expected_pages"] == 1
    assert batch.next_cursor["detail_attempted"] == 1
    assert batch.next_cursor["detail_missing"] == 1
    assert batch.next_cursor["detail_failed"] == 0
