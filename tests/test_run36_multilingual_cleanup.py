from app.jobs.discovery import classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str) -> RawJob:
    return RawJob(
        source_listing_id=title.casefold().replace(" ", "-"),
        url="https://example.invalid/job",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Wien", location_text="Wien, Austria")],
    )


def test_female_equal_opportunity_text_is_not_fem_evidence() -> None:
    decision = classify_job_candidate(
        _job(
            "Cloud Engineer",
            "We welcome female applicants and candidates of all backgrounds. Cloud platform role.",
        )
    )

    assert "fem_fea" not in decision.method_tool_matches
    assert decision.accepted is False


def test_explicit_fem_token_remains_engineering_evidence() -> None:
    decision = classify_job_candidate(
        _job(
            "Project Engineer",
            "Mechanical component development with FEM calculations and CAD validation.",
        )
    )

    assert "fem_fea" in decision.method_tool_matches
    assert decision.accepted is True


def test_finite_element_phrase_remains_engineering_evidence() -> None:
    decision = classify_job_candidate(
        _job(
            "Simulation Engineer",
            "Finite element analysis for mechanical assemblies and structural validation.",
        )
    )

    assert "fem_fea" in decision.method_tool_matches
    assert decision.accepted is True
