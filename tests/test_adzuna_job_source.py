from __future__ import annotations

import json

import httpx
import pytest

from app.sources.base import SourceFetchError
from app.sources.job.adzuna import AdzunaJobSource, AdzunaQuery, parse_adzuna_job


def test_parse_adzuna_job_preserves_source_identity_location_and_salary() -> None:
    item = {
        "id": "987654",
        "title": "Senior Konstrukteur Maschinenbau",
        "description": "Mechanische Konstruktion, CAD und Baugruppen.",
        "redirect_url": "https://www.adzuna.at/details/987654",
        "company": {"display_name": "Beispiel Maschinenbau GmbH"},
        "location": {
            "display_name": "1030 Wien, Wien",
            "area": ["Austria", "Wien", "1030 Wien"],
        },
        "salary_min": 60000,
        "salary_max": 72000,
        "salary_is_predicted": "0",
        "created": "2026-08-28T00:00:00Z",
        "latitude": 48.2,
        "longitude": 16.4,
    }

    job = parse_adzuna_job(item, query=AdzunaQuery("maschinenbau", "Maschinenbau"))

    assert job is not None
    assert job.source_listing_id == "adzuna:987654"
    assert job.company == "Beispiel Maschinenbau GmbH"
    assert job.salary_currency == "EUR"
    assert job.salary_period is None
    assert job.salary_provenance == "EXPLICIT"
    assert job.locations[0].postal_code == "1030"
    assert job.locations[0].city == "Wien"
    assert job.raw_payload["source_attribution"] == "Adzuna API"
    assert job.raw_payload["description_truncated_by_source"] is True


def test_predicted_adzuna_salary_is_not_treated_as_employer_explicit() -> None:
    item = {
        "id": "1",
        "title": "Mechanical Engineer",
        "description": "Mechanical design",
        "redirect_url": "https://www.adzuna.at/details/1",
        "salary_min": 50000,
        "salary_is_predicted": "1",
    }

    job = parse_adzuna_job(item, query=AdzunaQuery("mechanical", "Mechanical"))

    assert job is not None
    assert job.salary_provenance == "ESTIMATED"
    assert str(job.salary_confidence) == "0.500"


@pytest.mark.asyncio
async def test_fetch_shard_uses_one_official_api_request_and_never_claims_complete_coverage() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = {
            "count": 132,
            "results": [
                {
                    "id": "42",
                    "title": "Konstrukteur Maschinenbau",
                    "description": "CAD Konstruktion von Baugruppen",
                    "redirect_url": "https://www.adzuna.at/details/42",
                    "company": {"display_name": "Example GmbH"},
                    "location": {"display_name": "Linz", "area": ["Austria", "Linz"]},
                }
            ],
        }
        return httpx.Response(200, content=json.dumps(payload), request=request)

    adapter = AdzunaJobSource(
        app_id="test-id",
        app_key="test-secret",
        queries=[AdzunaQuery("maschinenbau", "Maschinenbau")],
        request_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    shard = adapter.default_shards()[0]

    batch = await adapter.fetch_shard(shard)

    assert len(requests) == 1
    assert requests[0].url.path == "/v1/api/jobs/at/search/1"
    assert requests[0].url.params["title_only"] == "Maschinenbau"
    assert requests[0].url.params["max_days_old"] == "30"
    assert batch.source_reported_count == 132
    assert batch.pages_fetched == 1
    assert batch.coverage_complete is False
    assert batch.items[0].source_listing_id == "adzuna:42"


@pytest.mark.asyncio
async def test_api_failure_does_not_leak_credentials_in_exception_text() -> None:
    secret = "do-not-leak-this-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(410, request=request)

    adapter = AdzunaJobSource(
        app_id="test-id",
        app_key=secret,
        queries=[AdzunaQuery("maschinenbau", "Maschinenbau")],
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SourceFetchError) as exc_info:
        await adapter.fetch_shard(adapter.default_shards()[0])

    assert "HTTP 410" in str(exc_info.value)
    assert secret not in str(exc_info.value)
