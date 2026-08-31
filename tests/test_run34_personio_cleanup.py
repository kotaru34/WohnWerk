from app.jobs.discovery import classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str | None = None) -> RawJob:
    return RawJob(
        source_listing_id=title.casefold().replace(" ", "-"),
        url=f"https://example.invalid/{title.casefold().replace(' ', '-')}",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Wien", location_text="Wien, Austria")],
    )


def test_building_services_engineer_has_cross_source_hkls_parity() -> None:
    decision = classify_job_candidate(_job("Ingenieur:in Gebäudetechnik / HKLS-Technik"))

    assert decision.accepted is True
    assert decision.reason == "engineering_role_with_domain"
    assert "engineer" in decision.adjacent_title_matches
    assert "building_services" in decision.domain_matches


def test_service_technician_is_rejected_despite_recruiting_boilerplate() -> None:
    decision = classify_job_candidate(
        _job(
            "Servicetechniker (m/w/d) Oberösterreich",
            "Mechanik, Wartung und Störungsbehebung. HR Recruiting Team beantwortet Fragen.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "service_technician" in decision.adjacent_title_matches
    assert "service_technician_trade" in decision.low_relevance_title_matches
    assert "mechanical" in decision.domain_matches
    assert "hr" in decision.negative_context_matches


def test_field_service_manager_with_commissioning_is_adjacent() -> None:
    decision = classify_job_candidate(
        _job(
            "Field Service Manager (m/w/d)",
            "Technische Inbetriebnahme und Betreuung der Anlagen. HR Recruiting unterstützt Bewerber.",
        )
    )

    assert decision.accepted is True
    assert decision.reason == "engineering_role_with_method"
    assert "field_service_manager" in decision.adjacent_title_matches
    assert "commissioning" in decision.method_tool_matches


def test_production_lead_with_compound_fertigung_is_adjacent() -> None:
    decision = classify_job_candidate(_job("Produktionsleiter Gerätefertigung (m/w/d)"))

    assert decision.accepted is True
    assert decision.reason == "engineering_role_with_domain"
    assert "production_lead" in decision.adjacent_title_matches
    assert "manufacturing_compound" in decision.domain_matches


def test_kfz_mechatroniker_trade_does_not_win_via_strong_mechatronik_pattern() -> None:
    decision = classify_job_candidate(
        _job(
            "KFZ-Mechatroniker:in (m/w/d)",
            "Fahrzeugdiagnose, Wartung und Reparatur in der Werkstatt.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "vehicle_workshop_trade" in decision.low_relevance_title_matches


def test_kfz_techniker_trade_is_structurally_rejected_even_with_vehicle_domain() -> None:
    decision = classify_job_candidate(
        _job(
            "KFZ-Techniker:in (m/w/d)",
            "Arbeiten an Fahrzeugen, Diagnose und Werkstattservice.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "vehicle_workshop_trade" in decision.low_relevance_title_matches


def test_hr_in_title_still_blocks_weak_project_manager_match() -> None:
    decision = classify_job_candidate(
        _job(
            "HR Project Manager",
            "Projektarbeit für Maschinenbau-Teams und Personalentwicklung.",
        )
    )

    assert decision.accepted is False
    assert "project_manager" in decision.adjacent_title_matches
    assert "maschinenbau" in decision.domain_matches
    assert "hr" in decision.negative_context_matches
