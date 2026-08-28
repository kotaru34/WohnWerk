from datetime import UTC, datetime
from decimal import Decimal

from app.jobs.merge import build_merge_plan
from app.models import Job, JobListing, JobLocation, ListingStatus


def _job(
    job_id: int,
    *,
    title: str,
    company: str,
    city: str | None = None,
    description: str | None = None,
    salary_min: Decimal | None = None,
) -> Job:
    now = datetime(2026, 8, 28, tzinfo=UTC)
    job = Job(
        id=job_id,
        title=title,
        company=company,
        description=description,
        salary_min=salary_min,
        salary_currency="EUR" if salary_min is not None else None,
        salary_period="month" if salary_min is not None else None,
        salary_payment_count=14 if salary_min is not None else None,
        salary_provenance="explicit" if salary_min is not None else None,
        salary_confidence=Decimal("0.900") if salary_min is not None else None,
        salary_min_eur_year=(salary_min * 14) if salary_min is not None else None,
        status=ListingStatus.ACTIVE,
        first_seen_at=now,
        last_seen_at=now,
    )
    job.listings = [
        JobListing(
            source_id=job_id,
            source_listing_id=f"listing-{job_id}",
            url=f"https://example.invalid/{job_id}",
            status=ListingStatus.ACTIVE,
            raw_payload={"wohnwerk_discovery_gate": {"accepted": True}},
            first_seen_at=now,
            last_seen_at=now,
        )
    ]
    if city:
        job.locations = [
            JobLocation(
                city=city,
                location_text=city,
                remote=False,
            )
        ]
    return job


def test_merge_plan_prefers_richer_duplicate_as_survivor() -> None:
    sparse = _job(
        10,
        title="Mechanischer Konstrukteur (m/w/d)",
        company="Example GmbH",
        city="Linz",
    )
    rich = _job(
        20,
        title="Mechanischer Konstrukteur (m/w/d)",
        company="Example GmbH",
        city="Linz",
        description="Mechanische Konstruktion und Produktentwicklung. " * 20,
        salary_min=Decimal(4200),
    )

    plan = build_merge_plan([sparse, rich], source_names={10: "a", 20: "b"})

    assert plan.safe is True
    assert plan.survivor_id == 20
    assert plan.absorbed_ids == (10,)
    assert plan.salary_source_job_id == 20


def test_merge_plan_blocks_generic_same_company_without_high_evidence() -> None:
    left = _job(
        10,
        title="Konstrukteur (m/w/d)",
        company="Example GmbH",
    )
    right = _job(
        20,
        title="Konstrukteur (m/w/d)",
        company="Example GmbH",
        city="Klagenfurt",
    )

    plan = build_merge_plan([left, right], source_names={10: "a", 20: "b"})

    assert plan.safe is False
    assert any("not connected by high-confidence" in blocker for blocker in plan.blockers)


def test_merge_plan_blocks_conflicting_salary_bundles() -> None:
    left = _job(
        10,
        title="Senior Konstrukteur Maschinenbau",
        company="Example GmbH",
        city="Linz",
        salary_min=Decimal(4000),
    )
    right = _job(
        20,
        title="Senior Konstrukteur Maschinenbau",
        company="Example GmbH",
        city="Linz",
        salary_min=Decimal(5000),
    )

    plan = build_merge_plan([left, right], source_names={10: "a", 20: "b"})

    assert plan.safe is False
    assert "conflicting canonical salary bundles across merge group" in plan.blockers
