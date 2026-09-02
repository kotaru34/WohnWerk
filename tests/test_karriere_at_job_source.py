from __future__ import annotations

import json

import httpx

from app.sources.job.karriere_at import (
    KarriereAtJobSource,
    KarriereSearch,
    parse_karriere_detail_page,
    parse_karriere_search_page,
    title_worth_detail,
)


def _detail_html() -> str:
    posting = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Konstrukteur / Entwicklungsingenieur Fahrzeugbau (m/w/d)",
        "description": (
            "<p>Entwicklung und Konstruktion von Fahrzeugen.</p>"
            "<ul><li>3D CAD mit SolidWorks</li><li>Bauteile und Baugruppen</li></ul>"
        ),
        "hiringOrganization": {"@type": "Organization", "name": "PEISCHL Fahrzeugbau GmbH"},
        "datePosted": "2026-08-18",
        "employmentType": "FULL_TIME",
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "EUR",
            "value": {"@type": "QuantitativeValue", "value": 3600, "unitText": "MONTH"},
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "postalCode": "7551",
                "addressLocality": "Stegersbach",
                "addressCountry": "AT",
            },
        },
    }
    return (
        "<html><head><title>Konstrukteur bei PEISCHL Fahrzeugbau GmbH | karriere.at</title>"
        f'<script type="application/ld+json">{json.dumps(posting)}</script>'
        "</head><body><h1>Konstrukteur</h1></body></html>"
    )


def test_search_parser_extracts_numeric_job_links_and_prefers_longer_title() -> None:
    content = """
    <html><body>
      <h1>275 Konstrukteur Maschinenbau Jobs</h1>
      <a href="/jobs/10027100"><span>Konstrukteur</span></a>
      <a href="https://www.karriere.at/jobs/10027100">Konstrukteur / Entwicklungsingenieur Fahrzeugbau</a>
      <a href="/jobs/10028000?foo=1">Elektrokonstrukteur</a>
      <a href="/firmen/example">Example GmbH</a>
    </body></html>
    """

    hits, reported = parse_karriere_search_page(content)

    assert reported == 275
    assert [hit.job_id for hit in hits] == ["10027100", "10028000"]
    assert hits[0].title == "Konstrukteur / Entwicklungsingenieur Fahrzeugbau"
    assert hits[0].url == "https://www.karriere.at/jobs/10027100"


def test_title_budget_prefilter_is_mechanical_not_electrical() -> None:
    assert title_worth_detail("Senior Konstrukteur Sondermaschinenbau (m/w/d)") is True
    assert title_worth_detail("Mechanical Design Engineer") is True
    assert title_worth_detail("Konstrukteur Elektrotechnik Fahrzeugbau") is False
    assert title_worth_detail("Senior Full-Stack Software Engineer") is False


def test_detail_parser_uses_jobposting_schema_without_inventing_location() -> None:
    job = parse_karriere_detail_page(
        _detail_html(),
        job_id="10027100",
        url="https://www.karriere.at/jobs/10027100",
        search_title="Konstrukteur Fahrzeugbau",
        search_label="Konstrukteur Maschinenbau",
    )

    assert job.source_listing_id == "karriere:10027100"
    assert job.company == "PEISCHL Fahrzeugbau GmbH"
    assert job.salary_min == 3600
    assert job.salary_max is None
    assert job.salary_currency == "EUR"
    assert job.salary_period == "month"
    assert job.salary_is_minimum_only is True
    assert "3D CAD mit SolidWorks" in (job.description or "")
    assert len(job.locations) == 1
    assert job.locations[0].postal_code == "7551"
    assert job.locations[0].city == "Stegersbach"
    assert job.raw_payload["detail_schema"] == "schema.org/JobPosting"


async def test_source_fetches_one_search_page_and_only_worthy_detail_pages() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/jobs/konstrukteur-maschinenbau":
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <h1>2 Konstrukteur Maschinenbau Jobs</h1>
                  <a href="/jobs/10027100">Konstrukteur / Entwicklungsingenieur Fahrzeugbau</a>
                  <a href="/jobs/10028000">Konstrukteur Elektrotechnik Fahrzeugbau</a>
                </body></html>
                """,
            )
        if request.url.path == "/jobs/10027100":
            return httpx.Response(200, text=_detail_html())
        raise AssertionError(f"unexpected request: {request.url}")

    adapter = KarriereAtJobSource(
        searches=[KarriereSearch("konstrukteur-maschinenbau", "Konstrukteur Maschinenbau")],
        request_delay_seconds=0,
        max_details_per_shard=8,
        transport=httpx.MockTransport(handler),
    )

    batch = await adapter.fetch_shard(adapter.default_shards()[0])

    assert len(batch.items) == 1
    assert batch.items[0].source_listing_id == "karriere:10027100"
    assert batch.coverage_complete is False
    assert batch.pages_fetched == 2
    assert batch.next_cursor["search_hits"] == 2
    assert batch.next_cursor["detail_candidates"] == 1
    assert batch.next_cursor["skipped_title"] == 1
    assert requests == [
        "https://www.karriere.at/jobs/konstrukteur-maschinenbau",
        "https://www.karriere.at/jobs/10027100",
    ]
