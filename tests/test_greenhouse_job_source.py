from app.sources.job.greenhouse import (
    EU_API_BASE,
    GLOBAL_API_BASE,
    GreenhouseBoard,
    GreenhouseJobSource,
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


def test_greenhouse_source_shards_and_regions_are_tenant_specific() -> None:
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
    assert source._api_base(source._board_from_shard(shards[0])) == EU_API_BASE
    assert source._api_base(source._board_from_shard(shards[1])) == GLOBAL_API_BASE
