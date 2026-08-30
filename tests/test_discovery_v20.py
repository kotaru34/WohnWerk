from app.jobs.discovery import DISCOVERY_GATE_VERSION, classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str | None = None) -> RawJob:
    return RawJob(
        source_listing_id=title,
        url="https://example.invalid/successfactors/job",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Weiz", location_text="Weiz, Styria, AT")],
    )


def test_v20_rejects_live_andritz_embedded_hardware_engineer() -> None:
    decision = classify_job_candidate(
        _job(
            "Hardware-Entwicklungsingenieur (m/w/d) für Embedded Systems",
            (
                "Automation R&D entwickelt elektronische Steuer- und Regelgeräte für "
                "Wasserkraftwerke. Elektrotechnik, Elektronik und Mikroelektronik."
            ),
        )
    )

    assert DISCOVERY_GATE_VERSION == "profile-seed-2026-08-30-v23"
    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "embedded_hardware_electronics" in decision.low_relevance_title_matches


def test_v20_keeps_live_andritz_project_manager_system_engineer_generator() -> None:
    decision = classify_job_candidate(
        _job(
            "Project Manager / System Engineer Generator (m/w/d)",
            (
                "Technische Ausbildung vorzugsweise Maschinenbau und Berufserfahrung "
                "im Projektgeschäft. Koordinierung der Auftragsabwicklung und "
                "Unterstützung des Sales Bereichs bei Offerten."
            ),
        )
    )

    assert decision.accepted is True
    assert decision.reason == "industrial_project_title"
    assert "rotating_equipment" in decision.domain_matches


def test_v20_keeps_live_andritz_spaced_german_project_manager() -> None:
    decision = classify_job_candidate(
        _job(
            "Projekt Manager (m/w/d) für Turbo Generatoren Service",
            (
                "Technische Ausbildung in Elektrotechnik oder Maschinenbau. "
                "Mehrjährige Erfahrung im Projektmanagement und Servicegeschäft."
            ),
        )
    )

    assert decision.accepted is True
    assert decision.reason == "industrial_project_title"
    assert "project_manager_de_spaced" in decision.adjacent_title_matches
    assert "rotating_equipment" in decision.domain_matches


def test_v20_keeps_live_andritz_mechanical_group_lead() -> None:
    decision = classify_job_candidate(
        _job(
            "Gruppenleiter Mechanical Plant Systems (m/w/d)",
            (
                "Technische Ausbildung im Bereich Maschinenbau oder Mechatronik. "
                "Einschlägige Berufserfahrung im Projektgeschäft."
            ),
        )
    )

    assert decision.accepted is True
    assert "group_lead_de" in decision.adjacent_title_matches
    assert "mechanical" in decision.domain_matches


def test_v20_does_not_rescue_sales_project_title() -> None:
    decision = classify_job_candidate(
        _job(
            "Project Manager Sales Turbo Generator",
            "Sales and commercial offer management for turbo generator projects.",
        )
    )

    assert decision.accepted is False
