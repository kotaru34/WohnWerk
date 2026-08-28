from __future__ import annotations

import json

import httpx
import pytest

from app.sources.base import SourceFetchError
from app.sources.job.jooble import JoobleJobSource, JoobleQuery, parse_jooble_job


def test_parse_jooble_job_preserves_identity_plz_and_source_provenance() -> None:
    item = {
        "id": 123456,
        "title": "Konstrukteur Maschinenbau",
        "location": "1030 Wien, Wien",
        "snippet": "Mechanische Konstruktion und CAD von Baugruppen.",
        "salary": "60.000 - 72.000 EUR",
        "source": "example.at",
        "type": "Vollzeit",
        "link": "https://at.jooble.org/jdp/123456",
        "company": "Beispiel Maschinenbau GmbH",
        "updated": "2026-08-28T00:00:00Z",
    }

    job = parse_jooble_job(item, query=JoobleQuery("maschinenbau", "Maschinenbau"))

    assert job is not None
    assert job.source_listing_id == "jooble:123456"
    assert job.company == "Beispiel Maschinenbau GmbH"
    assert job.salary_text == "60.000 - 72.000 EUR"
    assert job.salary_min is None
    assert job.locations[0].postal_code == "1030"
    assert job.locations[0].city == "Wien"
    assert job.raw_payload["jooble_source"] == "example.at"
    assert job.raw_payload["description_truncated_by_source"] is True


@pytest.mark.asyncio
async def test_fetch_shard_uses_one_regional_api_request_and_incomplete_coverage() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = {
            "totalCount": 541,
            "jobs": [
                {
                    "id": 77,
                    "title": "Senior Konstrukteur",
                    "location": "Linz",
                    "snippet": "CAD und mechanische Baugruppen",
                    "salary": "",
                    "source": "example.at",
                    "type": "Vollzeit",
                    "link": "https://at.jooble.org/jdp/77",
                    "company": "Example GmbH",
                    "updated": "2026-08-28T00:00:00Z",
                }
            ],
        }
        return httpx.Response(200, content=json.dumps(payload), request=request)

    adapter = JoobleJobSource(
        api_key="test-secret",
        queries=[JoobleQuery("konstrukteur", "Konstrukteur")],
        request_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    batch = await adapter.fetch_shard(adapter.default_shards()[0])

    assert len(requests) == 1
    assert requests[0].url.path == "/api/test-secret"
    body = json.loads(requests[0].content)
    assert body["keywords"] == "Konstrukteur"
    assert body["location"] == "Österreich"
    assert body["page"] == "1"
    assert batch.source_reported_count == 541
    assert batch.pages_fetched == 1
    assert batch.coverage_complete is False
    assert batch.items[0].source_listing_id == "jooble:77"


@pytest.mark.asyncio
async def test_api_failure_does_not_leak_path_api_key() -> None:
    secret = "do-not-leak-this-jooble-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, request=request)

    adapter = JoobleJobSource(
        api_key=secret,
        queries=[JoobleQuery("maschinenbau", "Maschinenbau")],
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SourceFetchError) as exc_info:
        await adapter.fetch_shard(adapter.default_shards()[0])

    assert "HTTP 403" in str(exc_info.value)
    assert secret not in str(exc_info.value)
