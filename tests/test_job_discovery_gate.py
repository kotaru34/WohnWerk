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
    assert decision.reason == "strong_mechanical_title"
    assert "konstruktionsingenieur" in decision.strong_title_matches


def test_technical_project_lead_in_product_development_is_accepted() -> None:
    decision = classify_job_candidate(
        _job(
            "Technischer Projektleiter Produktentwicklung",
            "Verantwortung für mechanische Baugruppen, Lieferantenkoordination, "
            "Lastenhefte, Terminplanung und Serienreife.",
        )
    )

    assert decision.accepted is True
    assert decision.reason == "engineering_role_with_domain"
    assert "technical_project_lead" in decision.adjacent_title_matches
    assert "product_development" in decision.domain_matches


def test_adjacent_application_engineer_with_cad_method_is_accepted() -> None:
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
    assert accepted.reason in {"engineering_role_with_domain", "engineering_role_with_method"}
    assert rejected.accepted is False


def test_rail_vehicle_fixture_role_is_kept() -> None:
    decision = classify_job_candidate(
        _job(
            "Project Engineer",
            "Entwicklung von Schweiß- und Montagevorrichtungen für Schienenfahrzeuge, "
            "technische Zeichnungen und Inbetriebnahme beim Lieferanten.",
        )
    )

    assert decision.accepted is True
    assert "rail_vehicle" in decision.domain_matches
    assert "fixture_tooling" in decision.domain_matches
    assert "technical_drawing" in decision.method_tool_matches


def test_autonomous_vehicle_technician_is_kept_as_adjacent_candidate() -> None:
    decision = classify_job_candidate(
        _job(
            "Senior Autonomous Vehicle Technician",
            "Diagnostics, calibration, vehicle maintenance, validation and technical operations.",
        )
    )

    assert decision.accepted is True
    assert "technician" in decision.adjacent_title_matches
    assert "vehicle_engineering" in decision.domain_matches


def test_autonomous_vehicle_driver_is_not_kept_on_vehicle_word_alone() -> None:
    decision = classify_job_candidate(
        _job(
            "Autonomous Vehicle Driver",
            "Drive autonomous vehicles on predefined routes and report incidents.",
        )
    )

    assert decision.accepted is False


def test_automotive_software_engineer_needs_real_mechanical_evidence() -> None:
    decision = classify_job_candidate(
        _job(
            "Software Engineer - Automotive",
            "Develop cloud backend services in Java and Kubernetes for automotive customers.",
        )
    )

    assert decision.accepted is False
    assert "software" in decision.negative_context_matches
    assert "vehicle_engineering" in decision.domain_matches


def test_sales_engineer_is_not_kept_from_automotive_context_alone() -> None:
    decision = classify_job_candidate(
        _job(
            "Sales Engineer Automotive",
            "Business development, account management and sales for automotive customers.",
        )
    )

    assert decision.accepted is False
    assert "sales" in decision.negative_context_matches


def test_generic_title_with_multiple_profile_methods_is_kept_for_recall() -> None:
    decision = classify_job_candidate(
        _job(
            "Technical Specialist",
            "CATIA V5, FEM, FMEA, PLM and validation of mechanical components.",
        )
    )

    assert decision.accepted is True
    assert decision.reason in {
        "engineering_role_with_domain",
        "engineering_role_with_method",
        "multiple_engineering_methods",
    }


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
    relevant = _job("Mechanical Design Engineer", "Creo CAD and FEM")
    unrelated = _job("HR Business Partner", "Recruiting and people operations")

    result = filter_job_candidates([relevant, unrelated])

    assert result == [relevant]
    evidence = relevant.raw_payload["wohnwerk_discovery_gate"]
    assert evidence["accepted"] is True
    assert evidence["reason"] == "strong_mechanical_title"
    assert "mechanical_design_engineer" in evidence["strong_title_matches"]
    assert "fem_fea" in evidence["method_tool_matches"]
    assert unrelated.raw_payload == {}
