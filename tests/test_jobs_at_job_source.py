import json

import httpx
import pytest

from app.sources.job.jobs_at import (
    JobsAtJobSource,
    JobsAtSearch,
    parse_jobs_at_detail_page,
    parse_jobs_at_search_page,
    title_worth_detail,
)


def test_parse_jobs_at_search_page_extracts_numeric_ids_and_count() -> None:
    content = """
    <html><body>
      <h1>320 aktuelle Mechanical Engineer Jobs</h1>
      <a href="/i/7874276">Mechanical Engineer (all genders)</a>
      <a href="https://www.jobs.at/i/7874001">Electrical Engineer (all genders)</a>
    </body></html>
    """

    hits, reported = parse_jobs_at_search_page(content)

    assert reported == 320
    assert [(hit.job_id, hit.title) for hit in hits] == [
        ("7874276", "Mechanical Engineer (all genders)"),
        ("7874001", "Electrical Engineer (all genders)"),
    ]


def test_jobs_at_title_prefilter_avoids_obvious_electrical_detail_requests() -> None:
    assert title_worth_detail("Senior Mechanical Design Engineer (m/w/d)")
    assert title_worth_detail("Konstrukteur / Entwicklungsingenieur Fahrzeugbau")
    assert not title_worth_detail("Electrical Engineer (all genders) Eplan P8")
    assert not title_worth_detail("E-Plan Konstrukteur (m/w/d) im Sondermaschinenbau")
    assert not title_worth_detail("E-Planer/in im Sondermaschinenbau")
    assert not title_worth_detail("Konstrukteur Elektrotechnik / Elektroplaner")


def test_parse_jobs_at_detail_prefers_source_postal_code_from_jobposting() -> None:
    posting = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Konstrukteur Maschinenbau (m/w/d)",
        "description": "<p>3D-CAD Konstruktion von Baugruppen.</p>",
        "hiringOrganization": {"@type": "Organization", "name": "Example GmbH"},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "postalCode": "1030",
                "addressLocality": "Wien",
                "addressRegion": "Wien",
                "addressCountry": "AT",
            },
        },
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "EUR",
            "value": {"@type": "QuantitativeValue", "minValue": 4200, "unitText": "MONTH"},
        },
    }
    content = (
        "<html><head><title>Konstrukteur Maschinenbau (m/w/d) bei Example GmbH - jobs.at</title>"
        f'<script type="application/ld+json">{json.dumps(posting)}</script></head>'
        "<body><h1>Konstrukteur Maschinenbau (m/w/d)</h1></body></html>"
    )

    job = parse_jobs_at_detail_page(
        content,
        job_id="1234567",
        url="https://www.jobs.at/i/1234567",
        search_title="Konstrukteur Maschinenbau (m/w/d)",
        search_label="Konstrukteur Maschinenbau",
    )

    assert job.source_listing_id == "jobsat:1234567"
    assert job.company == "Example GmbH"
    assert job.description == "3D-CAD Konstruktion von Baugruppen."
    assert job.salary_min is not None and str(job.salary_min) == "4200"
    assert job.salary_currency == "EUR"
    assert job.salary_period == "month"
    assert len(job.locations) == 1
    assert job.locations[0].postal_code == "1030"
    assert job.locations[0].city == "Wien"
    assert job.locations[0].location_text == "1030, Wien, Wien, AT"


def test_parse_jobs_at_visible_header_preserves_explicit_plz_without_jsonld() -> None:
    content = """
    <html><head>
      <title>Mechanical Engineer bei Example GmbH - jobs.at</title>
    </head><body>
      <h1>Mechanical Engineer</h1>
      <div>Example GmbH</div>
      <div>1030 Wien, Wien, AT - vor 2 T</div>
      <div>Vollzeit ab 4.200€ pro Monat Homeoffice</div>
      <h2>Aufgaben</h2>
      <p>Mechanical design and CAD modelling.</p>
      <a>Jetzt bewerben</a>
    </body></html>
    """

    job = parse_jobs_at_detail_page(
        content,
        job_id="7654321",
        url="https://www.jobs.at/i/7654321",
        search_title="Mechanical Engineer",
        search_label="Mechanical Engineer",
    )

    assert job.company == "Example GmbH"
    assert job.locations[0].postal_code == "1030"
    assert job.locations[0].city == "Wien"
    assert job.locations[0].location_text == "1030 Wien, Wien, AT"
    assert job.locations[0].remote is True
    assert job.salary_text == "ab 4.200€ pro Monat"


@pytest.mark.asyncio
async def test_jobs_at_frontier_dedupes_searches_and_only_opens_title_candidates() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/j/mechanical-engineer":
            return httpx.Response(
                200,
                text="""
                <h1>20 aktuelle Mechanical Engineer Jobs</h1>
                <a href="/i/1000001">Mechanical Engineer</a>
                <a href="/i/1000002">Electrical Engineer</a>
                """,
            )
        if request.url.path == "/j/konstrukteur-maschinenbau":
            return httpx.Response(
                200,
                text="""
                <h1>10 aktuelle Konstrukteur Maschinenbau Jobs</h1>
                <a href="/i/1000001">Mechanical Engineer</a>
                <a href="/i/1000003">Konstrukteur Maschinenbau</a>
                """,
            )
        job_id = request.url.path.rsplit("/", 1)[-1]
        title = "Mechanical Engineer" if job_id == "1000001" else "Konstrukteur Maschinenbau"
        posting = {
            "@type": "JobPosting",
            "title": title,
            "description": "Mechanical CAD design of components and assemblies.",
            "hiringOrganization": {"name": "Example GmbH"},
            "jobLocation": {
                "address": {
                    "addressLocality": "Linz",
                    "addressCountry": "AT",
                }
            },
        }
        return httpx.Response(
            200,
            text=(
                f'<script type="application/ld+json">{json.dumps(posting)}</script>'
                f"<h1>{title}</h1>"
            ),
        )

    adapter = JobsAtJobSource(
        searches=[
            JobsAtSearch("mechanical-engineer", "Mechanical Engineer"),
            JobsAtSearch("konstrukteur-maschinenbau", "Konstrukteur Maschinenbau"),
        ],
        request_delay_seconds=0,
        max_details_per_shard=8,
        transport=httpx.MockTransport(handler),
    )

    first, second = adapter.default_shards()
    first_batch = await adapter.fetch_shard(first)
    second_batch = await adapter.fetch_shard(second)

    assert [item.source_listing_id for item in first_batch.items] == ["jobsat:1000001"]
    assert [item.source_listing_id for item in second_batch.items] == ["jobsat:1000003"]
    assert requests == [
        "/j/mechanical-engineer",
        "/i/1000001",
        "/j/konstrukteur-maschinenbau",
        "/i/1000003",
    ]
    assert first_batch.coverage_complete is False
    assert second_batch.coverage_complete is False
