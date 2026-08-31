from app.jobs.discovery import DISCOVERY_GATE_VERSION, classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str) -> RawJob:
    return RawJob(
        source_listing_id=title,
        url="https://example.invalid/tgw/job",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Wels", location_text="Wels, Austria")],
    )


def test_v22_rejects_tgw_sales_engineer() -> None:
    decision = classify_job_candidate(
        _job(
            "Sales Engineer Retrofit (M/F/D)",
            "Technical retrofit proposals, customer consulting and sales for automated systems.",
        )
    )

    assert DISCOVERY_GATE_VERSION == "profile-seed-2026-08-30-v24"
    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "sales_title_role" in decision.low_relevance_title_matches


def test_v22_rejects_sales_application_engineer() -> None:
    decision = classify_job_candidate(
        _job(
            "Application Engineer (M/F/D)",
            "Key member of the international sales team responsible for technical project "
            "planning, quotations, proposals and customer consulting for intralogistics.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "commercial_sales_role"
    assert "sales_application_engineering" in decision.low_relevance_title_matches


def test_v22_rejects_tgw_test_technician() -> None:
    decision = classify_job_candidate(
        _job(
            "Technician Test Engineering (M/F/D)",
            "Assembly, installation and commissioning of mechanical test rigs and prototypes.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "technician_position" in decision.low_relevance_title_matches


def test_v22_rejects_tgw_installation_specialist_even_with_mechanical_title_text() -> None:
    decision = classify_job_candidate(
        _job(
            "Installation Specialist - Mechanical Engineering / Automation Technology (M/F/D)",
            "Coordinate assembly work, perform installation work yourself and support commissioning.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "installation_specialist" in decision.low_relevance_title_matches


def test_v22_rejects_tgw_eplan_electrical_design_role() -> None:
    decision = classify_job_candidate(
        _job(
            "E-Plan Design Engineer - Rovosphere (M/F/D)",
            "Electrical concepts, circuit diagrams, control cabinets and EPLAN Electric P8.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "pure_controls_electrical_title" in decision.low_relevance_title_matches


def test_v22_rejects_tgw_controls_support_role() -> None:
    decision = classify_job_candidate(
        _job(
            "Technical Support Engineer Controls (M/F/D)",
            "Support PLC control systems, automation technology and controls commissioning.",
        )
    )

    assert decision.accepted is False
    assert "pure_controls_electrical_title" in decision.low_relevance_title_matches


def test_v22_rejects_tgw_controls_project_manager() -> None:
    for title in (
        "Project Manager - Control Engineering (M/F/D)",
        "Project Manager Controls (M/F/D)",
        "Supervisor / assembly manager in control technology (M/F/D)",
    ):
        decision = classify_job_candidate(
            _job(
                title,
                "Control technology, PLC implementation, electrical automation and commissioning.",
            )
        )
        assert decision.accepted is False, title
        assert "pure_controls_electrical_title" in decision.low_relevance_title_matches


def test_v22_keeps_tgw_mechanical_support_engineer() -> None:
    decision = classify_job_candidate(
        _job(
            "Technical Support Engineer Mechanics (M/F/D)",
            "Technical support for mechanics, mechanical components, diagnostics and commissioning.",
        )
    )

    assert decision.accepted is True
    assert "mechanics" in decision.domain_matches


def test_v22_keeps_tgw_cross_discipline_r_and_d_project_manager() -> None:
    decision = classify_job_candidate(
        _job(
            "Project Manager (M/F/D)",
            "Manage innovative mechatronics product development projects from conception through "
            "series launch. Own deadlines, resources, budgets and risk management across software "
            "and mechatronics teams using agile methods, Scrum, PMA and MS Project.",
        )
    )

    assert decision.accepted is True
    assert decision.reason == "technical_project_management_body"
    assert "mechatronics" in decision.domain_matches


def test_v22_keeps_tgw_mechatronics_product_project_manager() -> None:
    decision = classify_job_candidate(
        _job(
            "Strategic (Senior) Project Manager – Mechatronics Product Development (M/F/D)",
            "Lead strategic technological projects in mechatronics product development with "
            "interface management and international stakeholders.",
        )
    )

    assert decision.accepted is True
    assert decision.reason == "industrial_project_title"


def test_v22_keeps_tgw_overall_project_manager_new_installations() -> None:
    decision = classify_job_candidate(
        _job(
            "Overall Project Manager for New Installations (M/F/D)",
            "Overall responsibility for automated distribution-center projects including cost, "
            "schedule and quality, supplier coordination, functional specifications, assembly, "
            "commissioning and testing. Mechanical or mechatronics education required.",
        )
    )

    assert decision.accepted is True
