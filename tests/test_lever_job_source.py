from decimal import Decimal

from app.sources.job.lever import LeverJobSource, LeverSite, parse_lever_posting


def _base_payload() -> dict:
    return {
        "id": "abc123",
        "text": "Mechanical Design Engineer",
        "hostedUrl": "https://jobs.eu.lever.co/example/abc123",
        "applyUrl": "https://jobs.eu.lever.co/example/abc123/apply",
        "country": "AT",
        "categories": {
            "location": "Graz",
            "allLocations": ["Graz"],
        },
        "workplaceType": "hybrid",
        "descriptionPlain": "Develop mechanical assemblies.",
        "lists": [
            {
                "text": "Requirements",
                "content": "<ul><li>Creo</li><li>CAD</li></ul>",
            }
        ],
        "additionalPlain": "English and German are useful.",
        "salaryRange": {
            "min": 60000,
            "max": 76000,
            "currency": "EUR",
            "interval": "per-year-salary",
        },
        "salaryDescriptionPlain": "EUR 60,000-76,000 gross per year",
    }


def test_parse_austrian_lever_posting_with_structured_salary() -> None:
    site = LeverSite(site="example", company="Example GmbH", region="eu")

    job = parse_lever_posting(_base_payload(), site=site)

    assert job is not None
    assert job.source_listing_id == "eu:example:abc123"
    assert job.title == "Mechanical Design Engineer"
    assert job.company == "Example GmbH"
    assert job.salary_min == Decimal(60000)
    assert job.salary_max == Decimal(76000)
    assert job.salary_currency == "EUR"
    assert job.salary_period == "year"
    assert job.salary_payment_count is None
    assert job.salary_provenance == "EXPLICIT"
    assert job.salary_confidence == Decimal(1)
    assert "Develop mechanical assemblies." in (job.description or "")
    assert "Requirements\nCreo CAD" in (job.description or "")
    assert len(job.locations) == 1
    assert job.locations[0].city == "Graz"
    assert job.locations[0].postal_code is None
    assert job.locations[0].remote is False


def test_non_austrian_lever_posting_is_filtered() -> None:
    payload = _base_payload()
    payload["country"] = "DE"
    payload["categories"] = {
        "location": "Munich",
        "allLocations": ["Munich, Germany"],
    }

    job = parse_lever_posting(
        payload,
        site=LeverSite(site="example", company="Example GmbH", region="eu"),
    )

    assert job is None


def test_mixed_location_posting_keeps_only_explicit_austrian_location() -> None:
    payload = _base_payload()
    payload["country"] = None
    payload["categories"] = {
        "location": "Europe",
        "allLocations": ["Munich, Germany", "Vienna, Austria"],
    }

    job = parse_lever_posting(
        payload,
        site=LeverSite(site="example", company="Example GmbH", region="global"),
    )

    assert job is not None
    assert len(job.locations) == 1
    assert job.locations[0].city == "Vienna"
    assert job.locations[0].location_text == "Vienna, Austria"


def test_monthly_salary_does_not_assume_fourteen_payments() -> None:
    payload = _base_payload()
    payload["salaryRange"] = {
        "min": 4200,
        "max": 5000,
        "currency": "EUR",
        "interval": "per-month-salary",
    }

    job = parse_lever_posting(
        payload,
        site=LeverSite(site="example", company="Example GmbH", region="eu"),
    )

    assert job is not None
    assert job.salary_period == "month"
    assert job.salary_payment_count is None


def test_austrian_postal_code_is_preserved_for_postgis_resolution() -> None:
    payload = _base_payload()
    payload["categories"] = {
        "location": "8010 Graz, Austria",
        "allLocations": ["8010 Graz, Austria"],
    }

    job = parse_lever_posting(
        payload,
        site=LeverSite(site="example", company="Example GmbH", region="eu"),
    )

    assert job is not None
    assert job.locations[0].postal_code == "8010"
    assert job.locations[0].city == "Graz"


def test_lever_source_shards_are_tenant_specific() -> None:
    source = LeverJobSource(
        sites=[
            LeverSite(site="alpha", company="Alpha GmbH", region="eu"),
            LeverSite(site="beta", company="Beta GmbH", region="global"),
        ]
    )

    shards = source.default_shards()

    assert [shard.key for shard in shards] == ["eu:alpha", "global:beta"]
    assert shards[0].params["company"] == "Alpha GmbH"
    assert shards[1].params["region"] == "global"
