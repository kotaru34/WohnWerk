from app.jobs.identity import (
    smartrecruiters_job_ad_identity,
    stable_identity_from_payload,
)
from app.sources.job.smartrecruiters import SmartRecruitersSite, parse_smartrecruiters_detail


def test_smartrecruiters_identity_is_tenant_plus_job_ad() -> None:
    assert smartrecruiters_job_ad_identity("AntonPaar1", "ad-123") == (
        "smartrecruiters:AntonPaar1:jobad:ad-123"
    )
    assert smartrecruiters_job_ad_identity("AntonPaar1", None) is None


def test_legacy_payload_derives_identity_without_explicit_backfill() -> None:
    payload = {
        "wohnwerk_smartrecruiters_tenant": "AntonPaar1",
        "smartrecruiters_job_ad_id": "ad-123",
    }
    assert stable_identity_from_payload(payload) == "smartrecruiters:AntonPaar1:jobad:ad-123"


def test_explicit_identity_wins_over_source_specific_fallback() -> None:
    payload = {
        "wohnwerk_stable_identity": "source:stable:1",
        "wohnwerk_smartrecruiters_tenant": "AntonPaar1",
        "smartrecruiters_job_ad_id": "ad-123",
    }
    assert stable_identity_from_payload(payload) == "source:stable:1"


def test_smartrecruiters_parser_attaches_stable_identity() -> None:
    site = SmartRecruitersSite(tenant="ExampleEngineering", company="Example GmbH")
    payload = {
        "id": "744000123456789",
        "uuid": "posting-uuid",
        "name": "Mechanical Engineer",
        "jobId": "job-123",
        "jobAdId": "ad-123",
        "location": {
            "city": "Graz",
            "region": "Steiermark",
            "country": "at",
            "remote": False,
        },
        "jobAd": {"sections": {}},
    }

    job = parse_smartrecruiters_detail(payload, site=site)

    assert job is not None
    assert job.source_listing_id == "ExampleEngineering:744000123456789"
    assert job.raw_payload["smartrecruiters_job_ad_id"] == "ad-123"
    assert job.raw_payload["wohnwerk_stable_identity"] == (
        "smartrecruiters:ExampleEngineering:jobad:ad-123"
    )
