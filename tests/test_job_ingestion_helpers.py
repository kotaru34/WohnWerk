from decimal import Decimal

from app.ingestion.jobs import _annual_eur_value, _enrich_locations, _merge_listing_payload
from app.jobs.location_resolution import LocalityResolution
from app.models import Job
from app.sources.base import RawJobLocation


def test_yearly_eur_salary_is_already_annual() -> None:
    value = _annual_eur_value(
        Decimal(72000),
        currency="EUR",
        period="year",
        payment_count=None,
    )

    assert value == Decimal(72000)


def test_monthly_salary_requires_explicit_payment_count() -> None:
    value = _annual_eur_value(
        Decimal(4500),
        currency="EUR",
        period="month",
        payment_count=None,
    )

    assert value is None


def test_monthly_salary_uses_explicit_payment_count() -> None:
    value = _annual_eur_value(
        Decimal(4500),
        currency="EUR",
        period="month",
        payment_count=14,
    )

    assert value == Decimal(63000)


def test_non_eur_salary_is_not_silently_normalized() -> None:
    value = _annual_eur_value(
        Decimal(90000),
        currency="USD",
        period="year",
        payment_count=None,
    )

    assert value is None


def test_sparse_job_discovery_preserves_detail_enrichment() -> None:
    existing = {
        "detail_enriched": True,
        "detail_description": "rich description",
        "detail_skills": ["Creo", "CAD"],
    }
    incoming = {
        "search_metadata_complete": False,
    }

    merged = _merge_listing_payload(existing, incoming)

    assert merged["detail_enriched"] is True
    assert merged["detail_description"] == "rich description"
    assert merged["detail_skills"] == ["Creo", "CAD"]
    assert merged["search_metadata_complete"] is False


def test_transient_job_detail_failure_does_not_downgrade_success() -> None:
    existing = {
        "detail_enriched": True,
        "detail_description": "rich description",
    }
    incoming = {
        "detail_enriched": False,
        "detail_enrichment_error": "temporary 503",
    }

    merged = _merge_listing_payload(existing, incoming)

    assert merged["detail_enriched"] is True
    assert merged["detail_description"] == "rich description"
    assert "detail_enrichment_error" not in merged
    assert merged["detail_enrichment_last_error"] == "temporary 503"


def test_remote_capable_job_keeps_source_provided_city_centroid() -> None:
    job = Job(title="Technical Project Manager")
    resolution = LocalityResolution(
        requested_city="Vienna",
        canonical_locality="wien",
        longitude=16.3738,
        latitude=48.2082,
        postal_codes=("1010", "1020"),
        address_sample_count=1000,
    )

    _enrich_locations(
        job,
        locations=[
            RawJobLocation(
                city="Vienna",
                location_text="Vienna, Austria",
                remote=True,
            )
        ],
        known_postal={},
        locality_resolutions={"Vienna": resolution},
    )

    assert len(job.locations) == 1
    assert job.locations[0].remote is True
    assert job.locations[0].city == "Vienna"
    assert job.locations[0].location is not None
