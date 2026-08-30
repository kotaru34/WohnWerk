from app.jobs.discovery import DISCOVERY_GATE_VERSION, classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str) -> RawJob:
    return RawJob(
        source_listing_id=title,
        url="https://example.invalid/greenhouse/job",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Steinhaus", location_text="Steinhaus, Austria")],
    )


def test_v19_rejects_gropyus_electrical_engineer_when_manufacturing_is_only_adjacent_domain() -> None:
    decision = classify_job_candidate(
        _job(
            "Electrical Engineer (all genders)",
            (
                "Electrical schematics with EPLAN, automation systems, control cabinets, "
                "technical calculations and commissioning support. The employer manufactures "
                "prefabricated building systems."
            ),
        )
    )

    assert DISCOVERY_GATE_VERSION == "profile-seed-2026-08-30-v23"
    assert decision.accepted is False
    assert decision.reason == "insufficient_base_relevance"
    assert "non_mechanical_electrical_engineering" in decision.low_relevance_title_matches


def test_v19_rejects_gropyus_german_electrical_engineer_with_eplan_and_automation() -> None:
    decision = classify_job_candidate(
        _job(
            "Elektroingenieur (m/w/d)",
            (
                "Elektropläne mit EPLAN, Automatisierungstechnik, Schaltschrankbau, "
                "technische Berechnung sowie Unterstützung bei Montage und Inbetriebnahme. "
                "Das Unternehmen arbeitet in der Fertigung."
            ),
        )
    )

    assert decision.accepted is False
    assert decision.reason == "insufficient_base_relevance"
    assert "non_mechanical_electrical_engineering" in decision.low_relevance_title_matches


def test_v19_keeps_automotive_electrical_engineer_with_vehicle_product_context() -> None:
    decision = classify_job_candidate(
        _job(
            "Electrical Engineer",
            (
                "Automotive vehicle electronics and product development with component "
                "integration, validation, FMEA and commissioning."
            ),
        )
    )

    assert decision.accepted is True
