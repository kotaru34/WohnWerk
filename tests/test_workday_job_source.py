import asyncio
from types import MethodType

from app.jobs.identity import stable_identity_from_payload
from app.refresh import SOURCE_REFRESH_PLANS
from app.sources.job.workday import WorkdayJobSource, WorkdaySite, parse_workday_detail


def _site() -> WorkdaySite:
    return WorkdaySite(
        tenant="magna",
        site="Magna",
        company="Magna",
        origin="https://magna.wd3.myworkdayjobs.com",
        locale="en-US",
        search_texts=("Austria",),
    )


def test_parse_workday_detail_preserves_exact_austrian_location_and_identity() -> None:
    job = parse_workday_detail(
        {
            "jobPostingInfo": {
                "title": "Sr. Engineer Electric Propulsion",
                "jobReqId": "R00253517",
                "jobPostingId": "posting-1",
                "jobDescription": "<p>Automotive <strong>product development</strong>.</p>",
                "location": "St. Valentin, AT",
                "additionalLocations": ["Graz, Austria", "Detroit, MI, United States"],
                "jobRequisitionLocation": {"country": {"alpha2Code": "AT"}},
                "timeType": "Full time",
            }
        },
        site=_site(),
        listing={
            "title": "Sr. Engineer Electric Propulsion",
            "externalPath": "/job/St-Valentin-AT/Sr-Engineer_R00253517-1",
            "locationsText": "St. Valentin, AT",
            "postedOn": "Posted 30+ Days Ago",
            "bulletFields": ["R00253517"],
        },
        austrian_localities={"st valentin", "graz"},
    )

    assert job is not None
    assert job.source_listing_id == "magna:Magna:R00253517"
    assert job.description == "Automotive product development ."
    assert [(row.city, row.location_text) for row in job.locations] == [
        ("St. Valentin", "St. Valentin, AT"),
        ("Graz", "Graz, Austria"),
    ]
    assert stable_identity_from_payload(job.raw_payload) == (
        "workday:magna:Magna:req:R00253517"
    )


def test_parse_workday_detail_rejects_foreign_only_posting() -> None:
    job = parse_workday_detail(
        {
            "jobPostingInfo": {
                "title": "Mechanical Engineer",
                "jobReqId": "R1",
                "location": "Detroit, Michigan, United States",
                "jobRequisitionLocation": {"country": {"alpha2Code": "US"}},
            }
        },
        site=_site(),
        listing={
            "title": "Mechanical Engineer",
            "externalPath": "/job/Detroit/Mechanical-Engineer_R1",
            "locationsText": "Detroit, Michigan, United States",
        },
        austrian_localities={"graz", "wien"},
    )

    assert job is None


def test_workday_search_shard_is_never_reconciliation_authority() -> None:
    adapter = WorkdayJobSource(
        sites=[_site()],
        austrian_localities={"st valentin", "graz"},
        request_delay_seconds=0,
    )

    async def fake_request_json(self, client, method, url, *, json_body=None):
        del self, client
        if method == "POST":
            assert url.endswith("/jobs")
            assert json_body is not None
            assert json_body["limit"] == 20
            assert json_body["searchText"] == "Austria"
            return {
                "total": 1,
                "jobPostings": [
                    {
                        "title": "Mechanical Design Engineer",
                        "externalPath": "/job/Graz/Mechanical-Design-Engineer_R9",
                        "locationsText": "Graz, Austria",
                        "postedOn": "Posted Today",
                    }
                ],
            }
        assert method == "GET"
        return {
            "jobPostingInfo": {
                "title": "Mechanical Design Engineer",
                "jobReqId": "R9",
                "jobDescription": "<p>CAD and mechanical product development</p>",
                "location": "Graz, Austria",
                "jobRequisitionLocation": {"country": {"alpha2Code": "AT"}},
            }
        }

    adapter._request_json = MethodType(fake_request_json, adapter)
    batch = asyncio.run(adapter.fetch_shard(adapter.default_shards()[0], reconciliation=True))

    assert len(batch.items) == 1
    assert batch.source_reported_count == 1
    assert batch.coverage_complete is False
    assert batch.result_cap_hit is False
    assert batch.next_cursor["search_text"] == "Austria"


def test_workday_scheduler_plan_has_no_reconciliation_authority() -> None:
    plan = next(
        row for row in SOURCE_REFRESH_PLANS if row.source_name == "workday-public-cxs"
    )

    assert plan.script == "scripts/run_workday_jobs.py"
    assert plan.supports_reconciliation is False
