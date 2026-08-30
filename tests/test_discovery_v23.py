from app.jobs.discovery import DISCOVERY_GATE_VERSION, classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str) -> RawJob:
    return RawJob(
        source_listing_id=title,
        url="https://example.invalid/palfinger/job",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Köstendorf", location_text="Köstendorf, Austria")],
    )


def test_v23_accepts_special_lifting_product_project_management() -> None:
    decision = classify_job_candidate(
        _job(
            "Projekt Manager - Special Lifting Solutions (m/w/d)",
            "Initiieren, Leiten und Steuern globaler Projekte für spezielle Hebelösungen. "
            "Gesamtverantwortung für komplexe Produkt- und Kundenentwicklungsprojekte "
            "mit Planung und Überwachung von Zeit, Budget und Ressourcen.",
        )
    )

    assert DISCOVERY_GATE_VERSION == "profile-seed-2026-08-30-v23"
    assert decision.accepted is True
    assert decision.reason == "industrial_project_title"
    assert "special_machinery" in decision.domain_matches


def test_v23_rejects_service_technician_compound_title() -> None:
    decision = classify_job_candidate(
        _job(
            "Servicetechniker Railway (w/m/d)",
            "Wartung, Reparatur, Störungsbehebung und Inbetriebnahme von Railway-Systemen "
            "beim Kunden mit hoher Reisetätigkeit.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "low_relevance_operational_title"
    assert "service_technician_trade" in decision.low_relevance_title_matches


def test_v23_rejects_maintenance_trade_even_with_engineering_methods() -> None:
    decision = classify_job_candidate(
        _job(
            "Instandhalter (w/m/d)",
            "Wartung, Instandhaltung und Störungsbehebung an Produktionsanlagen, "
            "inklusive Diagnostik, Testing und Inbetriebnahme.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "low_relevance_operational_title"
    assert "maintenance_trade" in decision.low_relevance_title_matches


def test_v23_rejects_electrical_assembly_team_lead() -> None:
    decision = classify_job_candidate(
        _job(
            "Teamleiter Montage Elektrik (w/m/d)",
            "Führung der Montage Elektrik, Ressourcenplanung, Qualität und technische "
            "Unterstützung in Elektrotechnik und Elektronik.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "low_relevance_operational_title"
    assert "electrical_assembly_lead" in decision.low_relevance_title_matches


def test_v23_keeps_shopfloor_management_broad_for_fit_ranking() -> None:
    decision = classify_job_candidate(
        _job(
            "Teamlead Shopfloor (w/m/d)",
            "Führung eines Shopfloor-Teams in Fertigung und Schweißerei mit Verantwortung "
            "für Produktivität, Qualität, Termine und kontinuierliche Verbesserung.",
        )
    )

    assert decision.accepted is True


def test_v23_does_not_expand_generic_lean_management() -> None:
    decision = classify_job_candidate(
        _job(
            "Experienced Plant Lean Manager (w/m/d)",
            "Leitung von KVP- und Lean-Initiativen in Produktion und Montage, 5S, "
            "Wertstromanalyse und Coaching von Shopfloor-Führungskräften.",
        )
    )

    assert decision.accepted is False
