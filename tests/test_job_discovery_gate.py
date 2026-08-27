from app.jobs.discovery import classify_job_candidate, filter_job_candidates
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str | None = None) -> RawJob:
    return RawJob(
        source_listing_id=title.casefold().replace(" ", "-"),
        url=f"https://example.invalid/{title.casefold().replace(' ', '-')}",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Graz", location_text="Graz, Austria")],
    )


def test_strong_mechanical_title_is_accepted_without_description() -> None:
    decision = classify_job_candidate(_job("Konstruktionsingenieur"))

    assert decision.accepted is True
    assert decision.reason == "strong_title"
    assert "konstruktion" in decision.strong_title_matches


def test_adjacent_application_engineer_needs_technical_support() -> None:
    accepted = classify_job_candidate(
        _job(
            "Application Engineer",
            "Customer-facing technical role using Creo and CAD for machine assemblies.",
        )
    )
    rejected = classify_job_candidate(
        _job(
            "Application Engineer",
            "Support enterprise SaaS customers and configure CRM workflows.",
        )
    )

    assert accepted.accepted is True
    assert accepted.reason == "adjacent_title_with_technical_support"
    assert rejected.accepted is False


def test_generic_title_with_multiple_mechanical_signals_is_kept_for_recall() -> None:
    decision = classify_job_candidate(
        _job(
            "Technical Specialist",
            "Responsible for CAD design in Creo, Konstruktion and Produktentwicklung.",
        )
    )

    assert decision.accepted is True
    assert decision.reason == "multiple_technical_signals"


def test_unrelated_finance_job_is_rejected() -> None:
    decision = classify_job_candidate(
        _job(
            "Senior Accountant",
            "Prepare monthly reports, tax filings and financial statements.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "insufficient_base_relevance"


def test_filter_persists_discovery_evidence_only_for_accepted_jobs() -> None:
    relevant = _job("Mechanical Design Engineer", "Creo CAD")
    unrelated = _job("HR Business Partner", "Recruiting and people operations")

    result = filter_job_candidates([relevant, unrelated])

    assert result == [relevant]
    evidence = relevant.raw_payload["wohnwerk_discovery_gate"]
    assert evidence["accepted"] is True
    assert evidence["reason"] == "strong_title"
    assert "mechanical_engineer" in evidence["strong_title_matches"]
    assert unrelated.raw_payload == {}
