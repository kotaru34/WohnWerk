from app.jobs.discovery import classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str | None = None) -> RawJob:
    return RawJob(
        source_listing_id=title,
        url="https://example.invalid/workday/job",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Graz", location_text="Graz, AT")],
    )


def test_v18_rejects_live_magna_academic_thesis() -> None:
    decision = classify_job_candidate(
        _job(
            "Bachelor-/Masterarbeit: Bewertung von Schraubflanschen",
            "Maschinenbau, FEM, Festigkeitsbewertung und Produktentwicklung.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "academic_thesis" in decision.low_relevance_title_matches


def test_v18_rejects_live_magna_unsolicited_application() -> None:
    decision = classify_job_candidate(
        _job(
            "Initiativbewerbung am Standort St. Valentin 2026 (m/w/x)",
            "Automotive, Produktentwicklung, Konstruktion, CAD und Projektmanagement.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "unsolicited_application" in decision.low_relevance_title_matches


def test_v18_rejects_live_magna_it_project_role() -> None:
    decision = classify_job_candidate(
        _job(
            "Program / Project Responsible IT (m/f/x)",
            "Automotive manufacturing, validation, requirements and project management.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "low_relevance_operational_title"
    assert "it_program_project_role" in decision.low_relevance_title_matches


def test_v18_rejects_live_magna_packaging_planner() -> None:
    decision = classify_job_candidate(
        _job(
            "Verpackungsplaner (m/w/x)",
            "Fertigung, Montage, CAD, Lieferantenkoordination und Produktentwicklung.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "low_relevance_operational_title"
    assert "packaging_planning" in decision.low_relevance_title_matches


def test_v18_keeps_live_magna_chassis_engineer() -> None:
    decision = classify_job_candidate(
        _job(
            "Entwicklungsingenieur_in Chassis Engineering – Automotive (m/w/x)",
            "Fahrzeugentwicklung, Konstruktion, CAD, FMEA und Validierung.",
        )
    )

    assert decision.accepted is True


def test_v18_keeps_live_magna_supplier_quality_development() -> None:
    decision = classify_job_candidate(
        _job(
            "Specialist Supplier Quality Development (m/w/x) mit Schwerpunkt Elektrik und Elektrikkomponenten",
            "Automotive product development, supplier management, FMEA and validation.",
        )
    )

    assert decision.accepted is True


def test_v18_keeps_live_magna_bodyshop_plant_planner() -> None:
    decision = classify_job_candidate(
        _job(
            "Anlagenplaner Karosseriebau (m/w/x)",
            "Anlagenbau, Fahrzeugbau, Fertigung, CAD und Inbetriebnahme.",
        )
    )

    assert decision.accepted is True


def test_v18_keeps_live_kion_commissioning_engineer() -> None:
    decision = classify_job_candidate(
        _job(
            "AGV Commissioning Engineer (w/m/d)",
            "Inbetriebnahme, Anlagenbau, Systemintegration und Validierung.",
        )
    )

    assert decision.accepted is True
