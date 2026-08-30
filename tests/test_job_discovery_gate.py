from app.jobs.discovery import (
    classify_job_candidate,
    filter_job_candidates,
    partition_job_candidates,
)
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
    assert decision.reason == "industrial_project_title"
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


def test_emc_engineer_is_kept_as_concrete_adjacent_engineering() -> None:
    decision = classify_job_candidate(
        _job(
            "EMC Engineer (w/m/d)",
            "EMV-gerechte Entwicklung, Planung und Bewertung von EMV-Tests, "
            "Schirmungs- und Filterkonzepte sowie Abstimmung mit Prüflaboren.",
        )
    )
    assert decision.accepted is True
    assert "engineer" in decision.adjacent_title_matches
    assert "emc_emv" in decision.method_tool_matches


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


def test_self_driving_systems_specialist_is_kept_for_diagnostics_and_calibration() -> None:
    decision = classify_job_candidate(
        _job(
            "Self-Driving Systems Specialist (SDS Specialist) - Autonomous Vehicle Diagnostics & Calibration",
            "Automotive electronics, sensors, diagnostics, calibration, validation, CAN bus and "
            "autonomous driving hardware.",
        )
    )
    assert decision.accepted is True
    assert "systems_specialist" in decision.adjacent_title_matches
    assert "autonomous_vehicle_systems" in decision.domain_matches
    assert "diagnostics" in decision.method_tool_matches
    assert "calibration" in decision.method_tool_matches


def test_depot_specialist_is_rejected_despite_vehicle_words() -> None:
    decision = classify_job_candidate(
        _job(
            "Depot Specialist (Robotaxi Fleet Operations)",
            "Prepare vehicles, clean, charge, inspect and stage them for daily fleet operations. "
            "Basic mechanical knowledge is preferred.",
        )
    )
    assert decision.accepted is False
    assert decision.reason == "low_relevance_operational_title"
    assert "depot_operations" in decision.low_relevance_title_matches


def test_autonomous_vehicle_test_operator_is_rejected() -> None:
    decision = classify_job_candidate(
        _job(
            "Autonomous vehicle Test Operator",
            "Operate and monitor autonomous vehicles, document rides and submit shift reports.",
        )
    )
    assert decision.accepted is False
    assert decision.reason == "low_relevance_operational_title"
    assert "vehicle_test_operator" in decision.low_relevance_title_matches


def test_autonomous_vehicle_driver_is_not_kept_on_vehicle_word_alone() -> None:
    decision = classify_job_candidate(
        _job(
            "Autonomous Vehicle Driver",
            "Drive autonomous vehicles on predefined routes and report incidents.",
        )
    )
    assert decision.accepted is False


def test_devsecops_security_tooling_is_not_mechanical_tooling() -> None:
    decision = classify_job_candidate(
        _job(
            "DevSecOps Engineer - Deployment Team",
            "Kubernetes security, cloud infrastructure, security tooling, CI/CD testing, "
            "Terraform and Python.",
        )
    )
    assert decision.accepted is False
    assert "software" in decision.negative_context_matches
    assert "fixture_tooling" not in decision.domain_matches


def test_generic_it_project_manager_is_not_promoted_by_system_integration() -> None:
    decision = classify_job_candidate(
        _job(
            "Projektmanager (f/m/d)",
            "Technologiegetriebene Entwicklungs- und Rollout-Projekte mit Fokus auf "
            "IT-Systemintegration. EDV-orientierte Ausbildung und langjährige Erfahrung "
            "in der Beratungs- und IT-Branche erforderlich.",
        )
    )
    assert decision.accepted is False
    assert "project_manager" in decision.adjacent_title_matches
    assert "system_integration" in decision.method_tool_matches
    assert "generic_it" in decision.negative_context_matches


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


def test_explicit_software_project_manager_is_rejected_despite_mechanical_company_context() -> None:
    decision = classify_job_candidate(
        _job(
            "Software Projektmanager (w/m/d)",
            "Projektmanagement für Software in einem Elektromobilitätsunternehmen mit "
            "mechanischer Produktentwicklung, Systemintegration, Validierung und OEM-Projekten.",
        )
    )
    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "software_role" in decision.low_relevance_title_matches


def test_ai_lead_is_rejected_despite_engineering_employer_boilerplate() -> None:
    decision = classify_job_candidate(
        _job(
            "Digital Engineering & AI Lead (f/m/d)",
            "Lead AI and software initiatives in an automotive charging company. The company "
            "also develops mechanical products, validates systems and works with OEMs.",
        )
    )
    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "ai_data_role" in decision.low_relevance_title_matches


def test_student_engineering_role_is_rejected_by_career_stage() -> None:
    decision = classify_job_candidate(
        _job(
            "Studentische:r Mitarbeiter:in Antriebstechnik & Motorenentwicklung",
            "Entwicklung elektrischer Antriebssysteme mit FEM, CAD, Simulation, Prototypen und Tests.",
        )
    )
    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "student_training_stage" in decision.low_relevance_title_matches


def test_working_student_strong_mechanical_title_is_still_rejected() -> None:
    decision = classify_job_candidate(
        _job(
            "Werkstudent Mechanical Engineer",
            "Mechanical design, CAD, FEM and prototype validation.",
        )
    )
    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "mechanical_engineer" in decision.strong_title_matches
    assert "student_training_stage" in decision.low_relevance_title_matches


def test_apprenticeship_constructor_is_rejected_before_strong_title_acceptance() -> None:
    decision = classify_job_candidate(
        _job(
            "Lehrausbildung Konstrukteur - Maschinenbautechnik",
            "Konstruktion von Maschinenbaukomponenten und technische Zeichnungen.",
        )
    )
    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "student_training_stage" in decision.low_relevance_title_matches


def test_compound_doppellehre_is_rejected_before_strong_title_acceptance() -> None:
    decision = classify_job_candidate(
        _job(
            "Doppellehre Maschinenbautechniker & Elektrotechniker (m/w/d) - 2027",
            "Ausbildung im Maschinenbau und in der Elektrotechnik.",
        )
    )
    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "maschinenbauingenieur" in decision.strong_title_matches
    assert "student_training_stage" in decision.low_relevance_title_matches


def test_explicit_graduate_role_is_rejected_for_experienced_corpus() -> None:
    decision = classify_job_candidate(
        _job(
            "TU/FH Absolvent (all gender)",
            "Karrierestart in Maschinen- und Anlagenbau, Konstruktion, Projektmanagement "
            "oder Inbetriebnahme mit erster Berufserfahrung durch Praktika.",
        )
    )
    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "graduate_entry_stage" in decision.low_relevance_title_matches


def test_manual_trade_titles_are_rejected_even_with_real_mechanical_work() -> None:
    for title in (
        "Metallfacharbeiter (w/m/div.)",
        "Mechaniker im Prüffeld (w/m/div)",
        "Metalltechniker / Schlosser (d/w/m)*",
    ):
        decision = classify_job_candidate(
            _job(
                title,
                "Fertigung mechanischer Bauteile nach technischen Zeichnungen, CNC, "
                "Messmittel, Montage und Qualitätsprüfung.",
            )
        )
        assert decision.accepted is False
        assert decision.reason == "low_relevance_operational_title"
        assert "manual_metal_trade" in decision.low_relevance_title_matches


def test_strong_mechanical_engineer_title_wins_over_incidental_ai_word() -> None:
    decision = classify_job_candidate(
        _job(
            "Mechanical Engineer - AI-assisted design tools",
            "Mechanical design, CAD, FEM and product development using AI-assisted tooling.",
        )
    )
    assert decision.accepted is True
    assert decision.reason == "strong_mechanical_title"


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
    assert evidence["version"]
    assert evidence["reason"] == "strong_mechanical_title"
    assert "mechanical_design_engineer" in evidence["strong_title_matches"]
    assert "fem_fea" in evidence["method_tool_matches"]
    assert unrelated.raw_payload == {}


def test_partition_persists_rejected_evidence_for_lifecycle_refresh() -> None:
    relevant = _job("Mechanical Design Engineer", "Creo CAD and FEM")
    rejected = _job("DevSecOps Engineer", "Kubernetes, Terraform and cloud security tooling")
    accepted_items, rejected_items = partition_job_candidates([relevant, rejected])
    assert accepted_items == [relevant]
    assert rejected_items == [rejected]
    accepted_gate = relevant.raw_payload["wohnwerk_discovery_gate"]
    rejected_gate = rejected.raw_payload["wohnwerk_discovery_gate"]
    assert accepted_gate["accepted"] is True
    assert rejected_gate["accepted"] is False
    assert rejected_gate["version"] == accepted_gate["version"]
    assert rejected_gate["reason"] == "insufficient_base_relevance"
