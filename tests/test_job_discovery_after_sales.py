from app.jobs.discovery import classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str) -> RawJob:
    return RawJob(
        source_listing_id="after-sales-case",
        url="https://example.invalid/after-sales-case",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Linz", location_text="Linz, Austria")],
    )


def test_after_sales_service_does_not_turn_field_service_engineer_commercial() -> None:
    decision = classify_job_candidate(
        _job(
            "Field Service Engineer – Pharma & Life Sciences",
            "Service and maintenance of measuring instruments, commissioning, "
            "troubleshooting and fault rectification. After-sales service including "
            "active customer support.",
        )
    )

    assert decision.accepted is True
    assert "engineer" in decision.adjacent_title_matches
    assert "commissioning" in decision.method_tool_matches
    assert "diagnostics" in decision.method_tool_matches
    assert "sales" not in decision.negative_context_matches


def test_actual_sales_engineer_remains_commercial_negative_context() -> None:
    decision = classify_job_candidate(
        _job(
            "Sales Engineer Automotive",
            "Business development, account management and sales for automotive customers.",
        )
    )

    assert decision.accepted is False
    assert "sales" in decision.negative_context_matches
