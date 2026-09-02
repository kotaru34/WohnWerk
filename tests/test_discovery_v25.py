from app.jobs.discovery import DISCOVERY_GATE_VERSION, classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str) -> RawJob:
    return RawJob(
        source_listing_id=title,
        url="https://example.invalid/palfinger/job",
        title=title,
        company="PALFINGER",
        description=description,
        locations=[RawJobLocation(city="Bergheim", location_text="5101 Bergheim, AT")],
    )


def test_v25_rejects_enterprise_application_management_even_with_plm_evidence() -> None:
    decision = classify_job_candidate(
        _job(
            "Team Lead Application Management PLM&E (f/m/d)",
            "Lead the global rollout and integration of the company-wide PLM solution, "
            "manage Teamcenter and SAP interfaces, external IT service providers, budgets, "
            "digital transformation and process optimization for engineering applications.",
        )
    )

    assert DISCOVERY_GATE_VERSION == "profile-seed-2026-08-30-v25"
    assert "enterprise_application_management" in decision.low_relevance_title_matches
    assert "plm" in decision.method_tool_matches
    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"


def test_v25_rejects_shopfloor_teamlead_even_with_manufacturing_evidence() -> None:
    decision = classify_job_candidate(
        _job(
            "Teamlead Shopfloor (w/m/d)",
            "Direct leadership of around 40 manufacturing engineering employees including "
            "welders, CNC specialists and robot operators. Responsible for production flow, "
            "productivity, quality and continuous improvement on the shopfloor.",
        )
    )

    assert "shopfloor_operations_lead" in decision.low_relevance_title_matches
    assert "manufacturing" in decision.domain_matches
    assert decision.accepted is False
    assert decision.reason == "low_relevance_operational_title"


def test_v25_keeps_technical_application_engineer_without_application_management_title() -> None:
    decision = classify_job_candidate(
        _job(
            "Application Engineer - Mechanical Systems (f/m/d)",
            "Mechanical engineering of crane systems with CAD, requirements, validation "
            "and technical customer integration."
        )
    )

    assert "enterprise_application_management" not in decision.low_relevance_title_matches
    assert "application_engineer" in decision.adjacent_title_matches
    assert decision.accepted is True


def test_v25_keeps_production_manager_with_engineering_domain() -> None:
    decision = classify_job_candidate(
        _job(
            "Production Manager (f/m/d)",
            "Lead manufacturing engineering and product development for mechanical assemblies, "
            "including process validation, FMEA and technical production planning."
        )
    )

    assert "shopfloor_operations_lead" not in decision.low_relevance_title_matches
    assert "production_lead" in decision.adjacent_title_matches
    assert decision.accepted is True


def test_v25_keeps_palfinger_development_engineer_service_diagnostic_tools() -> None:
    decision = classify_job_candidate(
        _job(
            "Development Engineer - Service & Diagnostic Tools (w/m/d)",
            "Technical development of service and diagnostic tools, requirements analysis, "
            "CAD design, testing, validation and error analysis for mechanical products."
        )
    )

    assert "service_technician_trade" not in decision.low_relevance_title_matches
    assert "development_engineer" in decision.adjacent_title_matches
    assert decision.accepted is True
