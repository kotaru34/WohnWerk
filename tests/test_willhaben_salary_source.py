from decimal import Decimal

import httpx
import pytest

from app.jobs.salary import parse_salary_text
from app.sources.job.willhaben_jobs import WillhabenSearch
from app.sources.job.willhaben_salary import WillhabenJobSource


@pytest.mark.asyncio
async def test_willhaben_salary_detail_keeps_overpayment_clause() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/jobs/suche/konstrukteur":
            return httpx.Response(
                200,
                text="""
                <h1>83 Jobs für Konstrukteur</h1>
                <a href="/jobs/job/senior-konstrukteur-mit-option-teamleitung-m-w-d/13261315">
                  SENIOR KONSTRUKTEUR MIT OPTION TEAMLEITUNG (m/w/d)
                </a>
                <a href="/jobs/firma/isg">ISG Personalmanagement GmbH Jobs</a>
                <div>28.08. | Vollzeit, Klagenfurt am Wörthersee</div>
                """,
            )
        if request.url.path.endswith("/13261315"):
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <div>Bruttogehalt:</div>
                  <div>€ 5.000 monatlich, mit Bereitschaft zur Überzahlung</div>
                </body></html>
                """,
            )
        return httpx.Response(404)

    adapter = WillhabenJobSource(
        searches=[WillhabenSearch("konstrukteur", "Konstrukteur")],
        request_delay_seconds=0,
        max_details_per_shard=1,
        transport=httpx.MockTransport(handler),
    )

    batch = await adapter.fetch_shard(adapter.default_shards()[0])

    assert requests == [
        "/jobs/suche/konstrukteur",
        "/jobs/job/senior-konstrukteur-mit-option-teamleitung-m-w-d/13261315",
    ]
    assert batch.next_cursor["details_fetched"] == 1
    assert batch.next_cursor["details_failed"] == 0
    parsed = parse_salary_text(batch.items[0].salary_text, trusted=True)
    assert parsed is not None
    assert str(parsed.minimum) == "5000"
    assert parsed.period == "month"
    assert parsed.minimum_only is True


@pytest.mark.asyncio
async def test_willhaben_salary_detail_follows_discovery_gate_not_title_regex() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/jobs/suche/maschinenbau":
            return httpx.Response(
                200,
                text="""
                <h1>25 Jobs für Maschinenbau</h1>
                <a href="/jobs/job/zerspanungstechniker-m-w-d/13262726">
                  Zerspanungstechniker (m/w/d)
                </a>
                <a href="/jobs/firma/akzente">AKZENTE PersonalbereitstellungsgesmbH Jobs</a>
                <div>01.09. | Vollzeit, Neunkirchen</div>
                <p>
                  Mechanische Konstruktion und Produktentwicklung im Maschinenbau mit CAD,
                  FEM, technischen Baugruppen, Fertigungsprozessen und Projektarbeit für
                  anspruchsvolle industrielle Komponenten.
                </p>
                """,
            )
        if request.url.path.endswith("/13262726"):
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <div>Bruttogehalt:</div>
                  <div>€ 17,50 stündlich, mit Bereitschaft zur Überzahlung</div>
                </body></html>
                """,
            )
        return httpx.Response(404)

    adapter = WillhabenJobSource(
        searches=[WillhabenSearch("maschinenbau", "Maschinenbau")],
        request_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    batch = await adapter.fetch_shard(adapter.default_shards()[0])

    assert requests == [
        "/jobs/suche/maschinenbau",
        "/jobs/job/zerspanungstechniker-m-w-d/13262726",
    ]
    assert batch.next_cursor["salary_detail_candidates"] == 1
    assert batch.next_cursor["salary_detail_selected"] == 1
    assert batch.next_cursor["salary_detail_limit"] is None
    assert batch.next_cursor["details_fetched"] == 1
    parsed = parse_salary_text(batch.items[0].salary_text, trusted=True)
    assert parsed is not None
    assert parsed.minimum == Decimal("17.50")
    assert parsed.period == "hour"
    assert parsed.minimum_only is True
