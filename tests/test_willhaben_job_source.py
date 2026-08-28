import httpx
import pytest

from app.sources.job.willhaben_jobs import (
    WillhabenJobSource,
    WillhabenSearch,
    parse_willhaben_search_page,
)


def test_parse_willhaben_search_card_fields_and_postal_code() -> None:
    content = """
    <html><body>
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
