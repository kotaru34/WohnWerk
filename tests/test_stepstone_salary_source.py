import httpx
import pytest

from app.jobs.salary import parse_salary_text
from app.sources.base import RawJob, SourceBatch
from app.sources.job.stepstone_at import StepStoneAtJobSource as SearchCardStepStoneAtJobSource
from app.sources.job.stepstone_at import StepStoneSearch
from app.sources.job.stepstone_salary import StepStoneAtJobSource


@pytest.mark.asyncio
async def test_stepstone_fetches_bounded_salary_detail() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/jobs/konstrukteur-maschinenbau":
            return httpx.Response(
                200,
                text="""
                <h1>20 Treffer</h1>
                <a href="/stellenangebote--Senior-Konstrukteur-Wien-Example--991405-inline.html">
                  Senior Konstrukteur (all genders), Maschinenbau – Mechanische Komponenten
                </a>
                <div>Flach &amp; Barfigo Personalleasing GmbH</div>
                <div>1030 Wien</div>
                <p>Mechanische Konstruktion von Komponenten und Baugruppen.</p>
                """,
            )
        if request.url.path.endswith("--991405-inline.html"):
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <p>Geboten wird ein monatliches Bruttogehalt von € 4.000,-- mit der
                  ausdrücklichen Bereitschaft zur Überzahlung je nach Qualifikation.</p>
                </body></html>
                """,
            )
        return httpx.Response(404)

    adapter = StepStoneAtJobSource(
        searches=[StepStoneSearch("konstrukteur-maschinenbau", "Konstrukteur Maschinenbau")],
        request_delay_seconds=0,
        max_details_per_shard=1,
        transport=httpx.MockTransport(handler),
    )

    batch = await adapter.fetch_shard(adapter.default_shards()[0])

    assert requests == [
        "/jobs/konstrukteur-maschinenbau",
        "/stellenangebote--Senior-Konstrukteur-Wien-Example--991405-inline.html",
    ]
    assert batch.next_cursor["details_fetched"] == 1
    assert batch.next_cursor["details_failed"] == 0
    assert batch.next_cursor["salary_details_found"] == 1
    assert batch.pages_fetched == 2
    parsed = parse_salary_text(batch.items[0].salary_text, trusted=True)
    assert parsed is not None
    assert str(parsed.minimum) == "4000"
    assert parsed.period == "month"
    assert parsed.minimum_only is True


@pytest.mark.asyncio
async def test_stepstone_default_enriches_more_than_old_eight_detail_budget(monkeypatch) -> None:
    items = [
        RawJob(
            source_listing_id=f"stepstone:{index}",
            url=f"https://www.stepstone.at/detail/{index}",
            title=f"Mechanical Engineer {index}",
            company="Example GmbH",
            description="Mechanical engineering and product development.",
        )
        for index in range(1, 10)
    ]

    async def fake_search_fetch(
        self,
        shard,
        *,
        cursor=None,
        reconciliation=False,
    ):
        del self, shard, cursor, reconciliation
        return SourceBatch(items=list(items), pages_fetched=1)

    monkeypatch.setattr(SearchCardStepStoneAtJobSource, "fetch_shard", fake_search_fetch)

    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(
            200,
            text="<p>EUR 3.700,00 brutto monatlich mit Bereitschaft zur Überzahlung</p>",
        )

    adapter = StepStoneAtJobSource(
        searches=[StepStoneSearch("mechanical", "Mechanical")],
        request_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    batch = await adapter.fetch_shard(adapter.default_shards()[0])

    assert adapter.max_details_per_shard is None
    assert batch.next_cursor["salary_detail_candidates"] == 9
    assert batch.next_cursor["salary_detail_selected"] == 9
    assert batch.next_cursor["salary_detail_limit"] is None
    assert batch.next_cursor["details_fetched"] == 9
    assert batch.next_cursor["salary_details_found"] == 9
    assert batch.pages_fetched == 10
    assert len(requests) == 9

    parsed = parse_salary_text(batch.items[-1].salary_text, trusted=True)
    assert parsed is not None
    assert str(parsed.minimum) == "3700.00"
    assert parsed.period == "month"
