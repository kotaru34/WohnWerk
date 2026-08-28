import httpx
import pytest

from app.sources.job.stepstone_at import (
    StepStoneAtJobSource,
    StepStoneSearch,
    parse_stepstone_search_page,
)


def test_parse_stepstone_search_page_extracts_card_fields_and_postal_code() -> None:
    content = """
    <html><body>
      <h1>331 Treffer für Konstrukteur/in Maschinenbau Jobs</h1>
      <a href="/stellenangebote--Senior-Konstrukteur-Wien-Example--123456-inline.html">
        Senior Konstrukteur (all genders), Maschinenbau – Mechanische Komponenten
      </a>
      <div>Example Engineering GmbH</div>
      <div>1030 Wien</div>
      <div>Schnelle Bewerbung</div>
      <p>Mechanische Konstruktion von Baugruppen und Komponenten mit 3D-CAD für Anlagenbauprojekte.</p>
      <span>mehr</span>
      <span>vor 2 Tagen</span>
    </body></html>
    """

    jobs, reported = parse_stepstone_search_page(
        content,
        search_label="Konstrukteur Maschinenbau",
    )

    assert reported == 331
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_listing_id == "stepstoneat:123456"
    assert job.company == "Example Engineering GmbH"
    assert job.locations[0].postal_code == "1030"
    assert job.locations[0].city == "Wien"
    assert "Mechanische Konstruktion" in (job.description or "")
    assert job.raw_payload["acquisition_level"] == "search-result-card"


def test_parse_stepstone_search_page_handles_whole_card_inside_anchor() -> None:
    long_description = (
        "Mechanische Konstruktion von Baugruppen und Komponenten mit 3D-CAD für "
        "anspruchsvolle Sondermaschinenbauprojekte. " * 8
    )
    content = f"""
    <html><body>
      <h1>321 Treffer für Konstrukteur Maschinenbau Jobs</h1>
      <a href="/stellenangebote--Konstrukteur-Kufstein-Vahle--223344-inline.html">
        <h2>Konstrukteur / Maschinenbautechniker (m/w/d)</h2>
        <div>VAHLE AUTOMATION GmbH</div>
        <div>6330 Kufstein</div>
        <p>{long_description}</p>
        <span>vor 1 Woche</span>
      </a>
    </body></html>
    """

    jobs, reported = parse_stepstone_search_page(
        content,
        search_label="Konstrukteur Maschinenbau",
    )

    assert reported == 321
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Konstrukteur / Maschinenbautechniker (m/w/d)"
    assert len(job.title) < 500
    assert job.company == "VAHLE AUTOMATION GmbH"
    assert job.locations[0].postal_code == "6330"
    assert job.locations[0].city == "Kufstein"
    assert "Sondermaschinenbauprojekte" in (job.description or "")


def test_parse_stepstone_search_page_handles_region_then_city_without_inventing_plz() -> None:
    content = """
    <a href="/stellenangebote--Maschinenbauingenieur-Modling-Example--987654-inline.html">
      Maschinenbauingenieur (m/w/d)
    </a>
    <div>Example GmbH</div>
    <div>Niederösterreich, Mödling</div>
    <p>Produktentwicklung und mechanische Konstruktion von Serienbauteilen.</p>
    """

    jobs, _ = parse_stepstone_search_page(content, search_label="Maschinenbauingenieur")

    assert len(jobs) == 1
    assert jobs[0].locations[0].postal_code is None
    assert jobs[0].locations[0].city == "Mödling"
    assert jobs[0].locations[0].location_text == "Niederösterreich, Mödling"


@pytest.mark.asyncio
async def test_stepstone_frontier_uses_one_request_per_search_and_cross_query_dedupe() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/jobs/konstrukteur-maschinenbau":
            return httpx.Response(
                200,
                text="""
                <h1>20 Treffer</h1>
                <a href="/stellenangebote--Mechanical-Engineer-Linz-A--100001-inline.html">
                  Mechanical Engineer
                </a>
                <div>A GmbH</div><div>Linz</div>
                <p>Mechanical design and CAD engineering of assemblies and components.</p>
                """,
            )
        return httpx.Response(
            200,
            text="""
            <h1>10 Treffer</h1>
            <a href="/stellenangebote--Mechanical-Engineer-Linz-A--100001-inline.html">
              Mechanical Engineer
            </a>
            <div>A GmbH</div><div>Linz</div>
            <p>Mechanical design and CAD engineering of assemblies and components.</p>
            <a href="/stellenangebote--Entwicklungsingenieur-Graz-B--100002-inline.html">
              Entwicklungsingenieur Maschinenbau
            </a>
            <div>B GmbH</div><div>Graz</div>
            <p>Produktentwicklung und Konstruktion mechanischer Baugruppen und Bauteile.</p>
            """,
        )

    adapter = StepStoneAtJobSource(
        searches=[
            StepStoneSearch("konstrukteur-maschinenbau", "Konstrukteur Maschinenbau"),
            StepStoneSearch("entwicklungsingenieur-maschinenbau", "Entwicklungsingenieur Maschinenbau"),
        ],
        request_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    first, second = adapter.default_shards()
    first_batch = await adapter.fetch_shard(first)
    second_batch = await adapter.fetch_shard(second)

    assert requests == [
        "/jobs/konstrukteur-maschinenbau",
        "/jobs/entwicklungsingenieur-maschinenbau",
    ]
    assert [item.source_listing_id for item in first_batch.items] == ["stepstoneat:100001"]
    assert [item.source_listing_id for item in second_batch.items] == ["stepstoneat:100002"]
    assert first_batch.next_cursor["details_fetched"] == 0
    assert second_batch.next_cursor["cross_query_duplicates"] == 1
    assert first_batch.coverage_complete is False
    assert second_batch.coverage_complete is False
