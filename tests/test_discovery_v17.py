from app.jobs.discovery import DISCOVERY_GATE_VERSION, classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str | None = None) -> RawJob:
    return RawJob(
        source_listing_id=title,
        url="https://example.invalid/job",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Graz", location_text="Graz, Austria")],
    )


def test_v17_rejects_live_anton_paar_cnc_turning_trade() -> None:
    decision = classify_job_candidate(
        _job(
            "CNC-Dreher (w/m/d)",
            "Fertigung, CAD-Zeichnungen, Qualitätskontrolle und CNC-Bearbeitung.",
        )
    )

    assert DISCOVERY_GATE_VERSION == "profile-seed-2026-08-30-v23"
    assert decision.accepted is False
    assert decision.reason == "low_relevance_operational_title"
    assert "cnc_turning_milling_trade" in decision.low_relevance_title_matches


def test_v17_rejects_live_anton_paar_flex_cnc_trade() -> None:
    decision = classify_job_candidate(
        _job(
            "Next Level Flexmodell für CNC-Dreher/-Fräser: 27 Stunden, 3 Nächte",
            "Serienfertigung, Prüfung, technische Zeichnungen und Maschinenbedienung.",
        )
    )

    assert decision.accepted is False
    assert "cnc_turning_milling_trade" in decision.low_relevance_title_matches


def test_v17_rejects_live_ims_laboratory_technician() -> None:
    decision = classify_job_candidate(
        _job(
            "Labortechniker:in Elektronik & Prototypenbau (all genders)",
            "Prototypenbau, Validierung, Testen und technische Dokumentation.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "low_relevance_operational_title"
    assert "laboratory_technician" in decision.low_relevance_title_matches


def test_v17_keeps_ims_manufacturing_engineer_hybrid_title() -> None:
    decision = classify_job_candidate(
        _job(
            "High Tech Assembler / Fertigungsingenieur:in High-Tech Manufacturing",
            "Fertigungsengineering, Prozessvalidierung, technische Zeichnungen und FMEA.",
        )
    )

    assert decision.accepted is True


def test_v17_keeps_quality_engineer_for_fit_engine_to_rank() -> None:
    decision = classify_job_candidate(
        _job(
            "Quality Engineer – Quality Assurance & Incoming Inspection",
            "Produktentwicklung, Fertigung, Validierung und technische Zeichnungen.",
        )
    )

    assert decision.accepted is True
