from decimal import Decimal

import httpx
import pytest

from app.sources.job.greenhouse import (
    EU_API_BASE,
    GLOBAL_API_BASE,
    GreenhouseBoard,
    GreenhouseJobSource,
    apply_greenhouse_pay_input_ranges,
    parse_greenhouse_posting,
)


def _base_payload() -> dict:
    return {
        "id": 4955941101,
        "title": "Mechanical Project Engineer",
        "location": {"name": "Vienna, Vienna, Austria"},
        "absolute_url": "https://job-boards.greenhouse.io/example/jobs/4955941101",
        "content": (
            "&amp;lt;p&amp;gt;Lead mechanical projects and supplier coordination."
            "&amp;lt;/p&amp;gt;"
        ),
        "company_name": "Example source company",
        "updated_at": "2026-08-30T12:00:00Z",
    }


def _austrian_pay_range() -> dict:
    return {
        "min_cents": 5_500_000,
        "max_cents": 6_000_000,
        "currency_type": "EUR",
        "title": "Austrian salary range, based on 14 months",
        "blurb": "",
    }


def test_parse_austrian_greenhouse_posting() -> None:
    board = GreenhouseBoard(token="example", company="Example GmbH")

    job = parse_greenhouse_posting(_base_payload(), board=board)

    assert job is not None
    assert job.source_listing_id == "global:example:4955941101"
    assert job.title == "Mechanical Project Engineer"
    assert job.company == "Example GmbH"
    assert job.url.endswith("/4955941101")
    assert job.description == "Lead mechanical projects and supplier coordination."
    assert len(job.locations) == 1
    assert job.locations[0].city == "Vienna"
    assert job.locations[0].location_text == "Vienna, Vienna, Austria"
    assert job.locations[0].remote is False
    assert job.raw_payload["wohnwerk_greenhouse_board"] == "example"


def test_greenhouse_austrian_14_month_pay_range_is_explicit_annual_salary() -> None:
    payload = _base_payload()
    payload["pay_input_ranges"] = [_austrian_pay_range()]

    job = parse_greenhouse_posting(
        payload,
        board=GreenhouseBoard(token="example", company="Example GmbH"),
    )

    assert job is not None
    assert job.salary_min == Decimal(55000)
    assert job.salary_max == Decimal(60000)
    assert job.salary_currency == "EUR"
    assert job.salary_period == "year"
    assert job.salary_payment_count is None
    assert job.salary_provenance == "STRUCTURED"
    assert job.salary_confidence == Decimal("1.000")
    assert job.salary_is_minimum_only is False
    assert job.raw_payload["wohnwerk_greenhouse_pay_period"] == "year"


def test_greenhouse_pay_range_without_period_is_not_invented() -> None:
    job = parse_greenhouse_posting(
        _base_payload(),
        board=GreenhouseBoard(token="example", company="Example GmbH"),
    )
    assert job is not None

    applied = apply_greenhouse_pay_input_ranges(
        job,
        {
            "pay_input_ranges": [
                {
                    "min_cents": 5_500_000,
                    "max_cents": 6_000_000,
                    "currency_type": "EUR",
                    "title": "Compensation range",
                }
            ]
        },
    )

    assert applied is False
    assert job.salary_min is None
    assert job.salary_period is None


def test_mixed_greenhouse_locations_keep_only_explicit_austria() -> None:
    payload = _base_payload()
    payload["location"] = {
        "name": "Berlin, Berlin, Germany; Graz, Austria; Ljubljana, Slovenia"
    }

    job = parse_greenhouse_posting(
        payload,
        board=GreenhouseBoard(token="example", company="Example GmbH"),
    )

    assert job is not None
    assert len(job.locations) == 1
    assert job.locations[0].city == "Graz"
    assert job.locations[0].location_text == "Graz, Austria"


def test_non_austrian_greenhouse_posting_is_filtered() -> None:
    payload = _base_payload()
    payload["location"] = {"name": "Munich, Bavaria, Germany"}

    job = parse_greenhouse_posting(
        payload,
        board=GreenhouseBoard(token="example", company="Example GmbH"),
    )

    assert job is None


def test_austria_remote_location_does_not_invent_city() -> None:
    payload = _base_payload()
    payload["location"] = {"name": "Austria, Remote"}

    job = parse_greenhouse_posting(
        payload,
        board=GreenhouseBoard(token="example", company="Example GmbH"),
    )

    assert job is not None
    assert job.locations[0].city is None
    assert job.locations[0].remote is True


def test_austrian_postal_code_is_preserved() -> None:
    payload = _base_payload()
    payload["location"] = {"name": "8010 Graz, Austria"}

    job = parse_greenhouse_posting(
        payload,
        board=GreenhouseBoard(token="example", company="Example GmbH"),
    )

    assert job is not None
    assert job.locations[0].postal_code == "8010"
    assert job.locations[0].city == "Graz"


def test_greenhouse_source_shards_keep_region_as_identity_not_api_host() -> None:
    source = GreenhouseJobSource(
        boards=[
            GreenhouseBoard(token="alpha", company="Alpha GmbH", region="eu"),
            GreenhouseBoard(token="beta", company="Beta GmbH", region="global"),
        ]
    )

    shards = source.default_shards()

    assert [shard.key for shard in shards] == ["alpha", "beta"]
    assert shards[0].params["region"] == "eu"
    assert shards[1].params["company"] == "Beta GmbH"
    assert EU_API_BASE == GLOBAL_API_BASE
    assert source._api_base(source._board_from_shard(shards[0])) == GLOBAL_API_BASE
    assert source._api_base(source._board_from_shard(shards[1])) == GLOBAL_API_BASE


@pytest.mark.asyncio
async def test_greenhouse_fetches_public_pay_transparency_for_relevant_austrian_job() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path, request.url.query.decode()))
        if request.url.path == "/v1/boards/example/jobs":
            return httpx.Response(200, json={"jobs": [_base_payload()]})
        if request.url.path == "/v1/boards/example/jobs/4955941101":
            detail = _base_payload()
            detail["pay_input_ranges"] = [_austrian_pay_range()]
            return httpx.Response(200, json=detail)
        return httpx.Response(404)

    source = GreenhouseJobSource(
        boards=[GreenhouseBoard(token="example", company="Example GmbH")],
        transport=httpx.MockTransport(handler),
    )

    batch = await source.fetch_shard(source.default_shards()[0])

    assert len(batch.items) == 1
    job = batch.items[0]
    assert job.salary_min == Decimal(55000)
    assert job.salary_max == Decimal(60000)
    assert job.salary_period == "year"
    assert batch.next_cursor["pay_detail_candidates"] == 1
    assert batch.next_cursor["pay_details_fetched"] == 1
    assert batch.next_cursor["pay_details_failed"] == 0
    assert batch.next_cursor["pay_ranges_found"] == 1
    assert batch.pages_fetched == 2
    assert any("pay_input_ranges=true" in query for _path, query in requests)
