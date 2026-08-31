from app.jobs.discovery import DISCOVERY_GATE_VERSION, classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str) -> RawJob:
    return RawJob(
        source_listing_id=title,
        url="https://example.invalid/job",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Wien", location_text="Wien, Austria")],
    )


def test_v24_service_technician_trade_overrides_incidental_strong_mechatronics_title() -> None:
    decision = classify_job_candidate(
        _job(
            "Servicetechniker (all genders) – Maschinenbau / Anlagenbau / Mechatronik",
            "Wartung, Reparatur, Störungsbehebung und Inbetriebnahme technischer Anlagen vor Ort.",
        )
    )

    assert DISCOVERY_GATE_VERSION == "profile-seed-2026-08-30-v25"
    assert "mechatronik" in decision.strong_title_matches
    assert "service_technician_trade" in decision.low_relevance_title_matches
    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"


def test_v24_field_service_manager_remains_adjacent_management_role() -> None:
    decision = classify_job_candidate(
        _job(
            "Field Service Manager (m/w/d)",
            "Technische Inbetriebnahme und Betreuung von Anlagen mit Team- und Projektverantwortung.",
        )
    )

    assert "service_technician_trade" not in decision.low_relevance_title_matches
    assert "field_service_manager" in decision.adjacent_title_matches
    assert decision.accepted is True


def test_v24_shopfloor_management_is_narrowed_by_live_palfinger_evidence() -> None:
    decision = classify_job_candidate(
        _job(
            "Teamlead Shopfloor (w/m/d)",
            "Führung eines Fertigungsteams mit Verantwortung für Qualität und Produktivität.",
        )
    )

    assert "electrical_assembly_lead" not in decision.low_relevance_title_matches
    assert "shopfloor_operations_lead" in decision.low_relevance_title_matches
    assert decision.accepted is False
    assert decision.reason == "low_relevance_operational_title"
