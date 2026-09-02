import httpx
import pytest

from app.jobs.salary import parse_salary_text
from app.sources.base import RawJob
from app.sources.job.willhaben_jobs import (
    WillhabenJobSource,
    WillhabenSearch,
    enrich_willhaben_detail_page,
    parse_willhaben_search_page,
)


def test_parse_willhaben_search_card_fields_and_postal_code() -> None:
    content = """
    <html><body>
      <div>Marktplatz 12.523.368 Immobilien 112.312 Auto &amp; Motor 206.355 Jobs 15.342</div>
      <h1>37 Jobs für CAD Zeichner</h1>
      <a href="/jobs/job/konstrukteur-senior-designer-m-w-d/13050655">
        Konstrukteur - Senior Designer (m/w/d)
      </a>
      <a href="/jobs/firma/kostwein">Kostwein Maschinenbau GmbH Jobs</a>
      <div>27.08. | Vollzeit, 9020 Klagenfurt am Wörthersee</div>
    </body></html>
    """

    jobs, reported = parse_willhaben_search_page(content, search_label="CAD Zeichner")

    assert reported == 37
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_listing_id == "willhabenjobs:13050655"
    assert job.title == "Konstrukteur - Senior Designer (m/w/d)"
    assert job.company == "Kostwein Maschinenbau GmbH"
    assert job.locations[0].postal_code == "9020"
    assert job.locations[0].city == "Klagenfurt am Wörthersee"
    assert job.raw_payload["published_label"] == "27.08."


def test_parse_willhaben_metadata_keeps_multi_part_location() -> None:
    content = """
    <h1>82 Anzeigen</h1>
    <a href="/jobs/job/cad-konstrukteur-hochbau/13050001">
      CAD Konstrukteur Hochbau (m/w/d)
    </a>
    <a href="/jobs/firma/example">Example GmbH Jobs</a>
    <div>26.08. | Teilzeit, Vollzeit, Wien, 01. Bezirk, Innere Stadt</div>
    """

    jobs, reported = parse_willhaben_search_page(content, search_label="Konstrukteur")

    assert reported == 82
    assert len(jobs) == 1
    assert jobs[0].locations[0].postal_code is None
    assert jobs[0].locations[0].city == "Wien"
    assert jobs[0].locations[0].location_text == "Wien, 01. Bezirk, Innere Stadt"


def test_parse_willhaben_whole_card_anchor_does_not_make_giant_title() -> None:
    snippet = (
        "Mechanische Konstruktion, Produktentwicklung und Auslegung von Baugruppen "
        "für Sondermaschinen und Anlagen. " * 8
    )
    content = f"""
    <h1>36 Anzeigen</h1>
    <a href="/jobs/job/konstrukteur-maschinenbau/13050002">
      <h2>Konstrukteur Maschinenbau (m/w/d)</h2>
      <div>Example Anlagenbau GmbH Jobs</div>
      <div>27.08. | Vollzeit, Weiz</div>
      <p>{snippet}</p>
    </a>
    """

    jobs, _ = parse_willhaben_search_page(content, search_label="Konstrukteur Maschinenbau")

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Konstrukteur Maschinenbau (m/w/d)"
    assert len(job.title) < 500
    assert job.company == "Example Anlagenbau GmbH"
    assert job.locations[0].city == "Weiz"
    assert "Produktentwicklung" in (job.description or "")


def test_willhaben_detail_extracts_explicit_monthly_salary() -> None:
    item = RawJob(
        source_listing_id="willhabenjobs:13261315",
        url=(
            "https://www.willhaben.at/jobs/job/"
            "senior-konstrukteur-mit-option-teamleitung-m-w-d/13261315"
        ),
        title="SENIOR KONSTRUKTEUR MIT OPTION TEAMLEITUNG (m/w/d)",
    )
    detail = """
    <html><body>
      <h1>SENIOR KONSTRUKTEUR MIT OPTION TEAMLEITUNG (m/w/d)</h1>
      <div>Bruttogehalt:</div>
      <div>€ 5.000 monatlich, mit Bereitschaft zur Überzahlung</div>
    </body></html>
    """

    enriched = enrich_willhaben_detail_page(item, detail)
    parsed = parse_salary_text(enriched.salary_text, trusted=True)

    assert enriched.raw_payload["detail_enriched"] is True
    assert enriched.raw_payload["willhaben_detail_salary_found"] is True
    assert parsed is not None
    assert str(parsed.minimum) == "5000"
    assert parsed.period == "month"
    assert parsed.minimum_only is True


@pytest.mark.asyncio
async def test_willhaben_frontier_uses_one_request_per_search_and_dedupes() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/jobs/suche/konstrukteur-maschinenbau":
            return httpx.Response(
                200,
                text="""
                <h1>36 Jobs für Konstrukteur Maschinenbau</h1>
                <a href="/jobs/job/mechanical-engineer/13050003">Mechanical Engineer</a>
                <a href="/jobs/firma/a">A GmbH Jobs</a>
                <div>27.08. | Vollzeit, Linz</div>
                """,
            )
        return httpx.Response(
            200,
            text="""
            <h1>83 Jobs für Konstrukteur</h1>
            <a href="/jobs/job/mechanical-engineer/13050003">Mechanical Engineer</a>
            <a href="/jobs/firma/a">A GmbH Jobs</a>
            <div>27.08. | Vollzeit, Linz</div>
            <a href="/jobs/job/entwicklungsingenieur/13050004">Entwicklungsingenieur Maschinenbau</a>
            <a href="/jobs/firma/b">B GmbH Jobs</a>
            <div>27.08. | Vollzeit, Graz</div>
            """,
        )

    adapter = WillhabenJobSource(
        searches=[
            WillhabenSearch("konstrukteur-maschinenbau", "Konstrukteur Maschinenbau"),
            WillhabenSearch("konstrukteur", "Konstrukteur"),
        ],
        request_delay_seconds=0,
        max_details_per_shard=0,
        transport=httpx.MockTransport(handler),
    )

    first, second = adapter.default_shards()
    first_batch = await adapter.fetch_shard(first)
    second_batch = await adapter.fetch_shard(second)

    assert requests == [
        "/jobs/suche/konstrukteur-maschinenbau",
        "/jobs/suche/konstrukteur",
    ]
    assert [item.source_listing_id for item in first_batch.items] == ["willhabenjobs:13050003"]
    assert [item.source_listing_id for item in second_batch.items] == ["willhabenjobs:13050004"]
    assert first_batch.next_cursor["details_fetched"] == 0
    assert second_batch.next_cursor["cross_query_duplicates"] == 1
    assert first_batch.coverage_complete is False
    assert second_batch.coverage_complete is False


@pytest.mark.asyncio
async def test_willhaben_fetches_bounded_detail_for_relevant_title() -> None:
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
    assert batch.pages_fetched == 2
    assert batch.items[0].salary_text is not None
