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


def test_gropyus_preflight_false_positive_titles_stay_out_of_mechanical_corpus() -> None:
    cases = {
        "Bauphysiker / Ingenieur für Bauphysik (m/w/d)": (
            "Bauphysik, thermische Gebäudehülle, Feuchteschutz und hygrothermische Simulation."
        ),
        "Building Physics Engineer (all genders)": (
            "Building physics, thermal comfort, moisture analysis and building envelope design."
        ),
        "Electrical Engineer (all genders)": (
            "Electrical building systems, switchgear, power distribution and equipment maintenance."
        ),
        "Elektroingenieur (m/w/d)": (
            "Elektrische Gebäudetechnik, Energieversorgung, Schaltanlagen und Instandhaltung."
        ),
        "Junior Projektmanager Anlagen- und Automatisierungstechnik (m/w/d)": (
            "Projektkoordination für Automatisierungstechnik, Inbetriebnahme und Terminplanung."
        ),
        "R&D Operations Manager (w/m/d)": (
            "Operational planning, resource coordination and process governance for R&D teams."
        ),
        "Senior Fire Safety Engineer (all genders)": (
            "Fire safety engineering, fire prevention concepts and regulatory building compliance."
        ),
        "Senior Manager Cost Optimization - Building System (Construction focus) (all genders)": (
            "Cost optimization for building systems, construction budgets and supplier cost analysis."
        ),
        "Senior Manager Cost Optimization – Building Systems (Schwerpunkt Bauwesen) (m/w/d)": (
            "Cost optimization for building systems with construction cost and procurement focus."
        ),
    }

    for title, description in cases.items():
        decision = classify_job_candidate(_job(title, description))
        assert decision.accepted is False, title


def test_electrical_engineering_needs_adjacent_mechanical_or_vehicle_domain() -> None:
    building = classify_job_candidate(
        _job(
            "Electrical Engineer",
            "Electrical building systems, switchgear and equipment maintenance.",
        )
    )
    automotive = classify_job_candidate(
        _job(
            "Electrical Engineer",
            "Design and development for automotive systems, verification and testing.",
        )
    )

    assert building.accepted is False
    assert "non_mechanical_electrical_engineering" in building.low_relevance_title_matches
    assert automotive.accepted is True


def test_strong_mechanical_title_still_wins_over_adjacent_exclusion_words() -> None:
    decision = classify_job_candidate(
        _job(
            "Mechanical Engineer - Electrical Systems",
            "Mechanical design, CAD, FEM, product development and validation.",
        )
    )

    assert decision.accepted is True
    assert decision.reason == "strong_mechanical_title"


def test_junior_generic_project_role_is_rejected_but_mechanical_title_keeps_recall() -> None:
    generic = classify_job_candidate(
        _job(
            "Junior Project Manager Automation",
            "Project coordination, commissioning and manufacturing systems.",
        )
    )
    mechanical = classify_job_candidate(
        _job(
            "Junior Mechanical Engineer",
            "Mechanical design, CAD, FEM and product development.",
        )
    )

    assert generic.accepted is False
    assert "junior_stage" in generic.low_relevance_title_matches
    assert mechanical.accepted is True
    assert mechanical.reason == "strong_mechanical_title"
