import httpx
import pytest

from app.jobs.salary import parse_salary_text
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
