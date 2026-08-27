import pytest

from app.sources.job.smartrecruiters import (
    SmartRecruitersJobSource,
    SmartRecruitersSite,
    parse_smartrecruiters_detail,
    parse_smartrecruiters_list,
)

SITE = SmartRecruitersSite(tenant="ExampleEngineering", company="Example Engineering GmbH")


def _detail(*, country: str = "at", title: str = "Mechanical Engineer") -> dict:
    return {
        "id": "744000123456789",
        "uuid": "5a7b33c7-3128-4fa3-b451-8aa72ef1c3ad",
        "name": title,
        "jobId": "job-123",
        "jobAdId": "ad-123",
        "refNumber": "REF123",
        "releasedDate": "2026-08-27T01:02:03.000Z",
        "company": {"identifier": "ExampleEngineering", "name": "Example Engineering GmbH"},
        "location": {
            "city": "Graz",
            "region": "Steiermark",
            "country": country,
            "remote": False,
        },
        "department": {"label": "R&D Engineering"},
        "function": {"label": "Engineering"},
        "industry": {"label": "Industrial Automation"},
        "typeOfEmployment": {"label": "Full-time"},
        "experienceLevel": {"label": "Mid-Senior Level"},
        "postingUrl": "https://jobs.smartrecruiters.com/ExampleEngineering/744000123456789-mechanical-engineer",
        "applyUrl": "https://jobs.smartrecruiters.com/ExampleEngineering/744000123456789-mechanical-engineer?apply=true",
        "jobAd": {
            "sections": {
                "companyDescription": {
                    "title": "Company Description",
                    "text": "<p>We also build cloud software and AI products.</p>",
                },
                "jobDescription": {
                    "title": "Job Description",
                    "text": "<p>Design mechanical assemblies from concept to series readiness.</p>",
                },
                "qualifications": {
                    "title": "Qualifications",
                    "text": "<p>CAD, SolidWorks and mechanical engineering experience.</p>",
                },
                "additionalInformation": {
                    "title": "Additional Information",
                    "text": "<p>Coordinate suppliers and validation activities.</p>",
                },
            }
        },
        "active": True,
    }


def test_parse_list_preserves_total_found() -> None:
    rows, total = parse_smartrecruiters_list(
        {
            "limit": 100,
            "offset": 0,
            "totalFound": 2,
            "content": [{"id": "1"}, {"id": "2"}],
        }
    )
    assert total == 2
    assert [row["id"] for row in rows] == ["1", "2"]


def test_parse_austrian_detail_builds_job_and_location() -> None:
    job = parse_smartrecruiters_detail(_detail(), site=SITE)
    assert job is not None
    assert job.source_listing_id == "ExampleEngineering:744000123456789"
    assert job.title == "Mechanical Engineer"
    assert job.company == "Example Engineering GmbH"
    assert job.locations[0].city == "Graz"
    assert job.locations[0].location_text == "Graz, Steiermark, Austria"
    assert job.locations[0].remote is False
    assert "Design mechanical assemblies" in (job.description or "")
    assert "CAD, SolidWorks" in (job.description or "")
    assert "cloud software and AI products" not in (job.description or "")
    assert job.raw_payload["smartrecruiters_department"] == "R&D Engineering"


def test_non_austrian_detail_is_rejected_defensively() -> None:
    assert parse_smartrecruiters_detail(_detail(country="de"), site=SITE) is None


def test_austria_country_name_is_accepted() -> None:
    job = parse_smartrecruiters_detail(_detail(country="Austria"), site=SITE)
    assert job is not None
    assert job.locations[0].city == "Graz"


def test_remote_austrian_posting_preserves_remote_flag() -> None:
    payload = _detail()
    payload["location"] = {
        "city": "Wien",
        "region": "Wien",
        "country": "at",
        "remote": True,
    }
    job = parse_smartrecruiters_detail(payload, site=SITE)
    assert job is not None
    assert job.locations[0].remote is True


@pytest.mark.asyncio
async def test_country_zero_can_fallback_to_unfiltered_detail_scan(monkeypatch) -> None:
    site = SmartRecruitersSite(
        tenant="ExampleEngineering",
        company="Example Engineering GmbH",
        unfiltered_austria_fallback=True,
    )
    source = SmartRecruitersJobSource(sites=[site], request_delay_seconds=0)
    shard = source.default_shards()[0]

    austrian = _detail(country="at", title="Mechanical Engineer")
    austrian["id"] = "at-1"
    german = _detail(country="de", title="Software Engineer")
    german["id"] = "de-1"

    async def fake_get_json(client, url, *, params=None):
        del client
        if url.endswith("/postings"):
            if params and params.get("country") == "at":
                return {"limit": 100, "offset": 0, "totalFound": 0, "content": []}
            return {
                "limit": 100,
                "offset": 0,
                "totalFound": 2,
                "content": [{"id": "at-1"}, {"id": "de-1"}],
            }
        if url.endswith("/at-1"):
            return austrian
        if url.endswith("/de-1"):
            return german
        raise AssertionError(url)

    monkeypatch.setattr(source, "_get_json", fake_get_json)
    batch = await source.fetch_shard(shard, reconciliation=True)

    assert batch.coverage_complete is True
    assert batch.pages_fetched == 2
    assert batch.source_reported_count is None
    assert [job.title for job in batch.items] == ["Mechanical Engineer"]
    assert batch.next_cursor["unfiltered_austria_fallback"] is True
    assert batch.next_cursor["fallback_unfiltered_reported"] == 2
    assert batch.next_cursor["fallback_austrian_postings"] == 1
    assert batch.next_cursor["detail_attempted"] == 2
    assert batch.next_cursor["detail_succeeded"] == 2
    assert batch.next_cursor["detail_failed"] == 0
    assert batch.next_cursor["detail_non_austrian"] == 1
