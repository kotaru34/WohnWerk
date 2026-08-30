from app.jobs.discovery import classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str) -> RawJob:
    return RawJob(
        source_listing_id=title.casefold().replace(" ", "-"),
        url="https://job-boards.greenhouse.io/example/jobs/1",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Vienna", location_text="Vienna, Austria")],
    )


def test_greenhouse_production_false_positive_titles_stay_out_of_mechanical_corpus() -> None:
    cases = {
        "DevSecOps Engineer": (
            "Cloud infrastructure, Kubernetes and Terraform. The employer also develops "
            "mechanical products using CAD, FMEA, validation and manufacturing processes."
        ),
        "DevOps Engineer": (
            "Operate software delivery infrastructure. Company-wide engineering includes "
            "CAD, FEM, validation, manufacturing and system integration."
        ),
        "Backend Engineer": (
            "Build Python backend services. Product teams also work on mechanical components, "
            "testing, validation, FMEA and manufacturing."
        ),
        "QA/RA Consultant": (
            "Quality and regulatory consulting with validation, FMEA, testing and technical "
            "documentation for regulated products."
        ),
        "Solution Delivery Engineer": (
            "Deliver customer software solutions with system integration, testing, "
            "commissioning and project coordination."
        ),
    }

    for title, description in cases.items():
        decision = classify_job_candidate(_job(title, description))
        assert decision.accepted is False, title


def test_generic_it_title_negative_beats_mechanical_employer_boilerplate() -> None:
    decision = classify_job_candidate(
        _job(
            "Backend Engineer",
            "Backend cloud services. Our wider company performs mechanical product development, "
            "CAD, FEM, FMEA, supplier coordination and validation.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "insufficient_base_relevance"
    assert "software" in decision.negative_context_matches


def test_qa_ra_and_solution_delivery_are_explicit_low_relevance_titles() -> None:
    qa = classify_job_candidate(
        _job("QA/RA Consultant", "FMEA, validation and technical documentation.")
    )
    delivery = classify_job_candidate(
        _job("Solution Delivery Engineer", "System integration, testing and commissioning.")
    )

    assert qa.accepted is False
    assert "qa_ra_regulatory" in qa.low_relevance_title_matches
    assert delivery.accepted is False
    assert "solution_delivery_engineer" in delivery.low_relevance_title_matches
