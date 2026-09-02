from app.jobs.discovery import classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str | None = None) -> RawJob:
    return RawJob(
        source_listing_id=title.casefold().replace(" ", "-"),
        url=f"https://example.invalid/{title.casefold().replace(' ', '-')}",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Graz", location_text="Graz, Austria")],
    )


def test_scaled_operational_and_business_titles_are_rejected() -> None:
    cases = {
        "Cutting machine operator (f/m/x)": "production_operator",
        "Operational purchaser (f/m/x)": "procurement_commercial",
        "Procurement Data & Process Developer": "procurement_commercial",
        "Senior Logistics Project Manager": "logistics_operations",
        "Expansion Project Manager": "expansion_management",
        "Schweißer – WIG / MAG (M/W/D) Bereich Industrie- & Ladenbau": "manual_metal_trade",
    }

    for title, expected_match in cases.items():
        decision = classify_job_candidate(
            _job(
                title,
                "Technical production environment with CAD drawings, suppliers, commissioning, "
                "testing, manufacturing and project coordination.",
            )
        )
        assert decision.accepted is False, title
        assert decision.reason == "low_relevance_operational_title", title
        assert expected_match in decision.low_relevance_title_matches, title


def test_field_service_engineer_stays_in_high_recall_neighbourhood() -> None:
    decision = classify_job_candidate(
        _job(
            "Field Service Engineer – Pharma & Life Sciences",
            "Service and maintenance of measuring instruments, commissioning, troubleshooting, "
            "fault rectification and technical customer support.",
        )
    )
    assert decision.accepted is True
    assert "engineer" in decision.adjacent_title_matches
    assert "commissioning" in decision.method_tool_matches
    assert "diagnostics" in decision.method_tool_matches


def test_technical_engineering_project_manager_stays_relevant() -> None:
    decision = classify_job_candidate(
        _job(
            "Technical Project Manager Engineering",
            "Industrialization and development projects in machine, plant and vehicle engineering; "
            "technical requirements, suppliers, system integration and verification.",
        )
    )
    assert decision.accepted is True
    assert "technical_project_lead" in decision.adjacent_title_matches


def test_work_preparation_team_lead_is_not_rejected_as_operator() -> None:
    decision = classify_job_candidate(
        _job(
            "Team Lead Work Preparation Machining (f/m/x)",
            "Lead technical work preparation for machining, manufacturing planning, drawings, "
            "process improvement and coordination with production engineering.",
        )
    )
    assert decision.accepted is True
    assert "production_operator" not in decision.low_relevance_title_matches
