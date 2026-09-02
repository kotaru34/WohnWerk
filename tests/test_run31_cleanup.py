from app.jobs.discovery import classify_job_candidate
from app.jobs.location_resolution import (
    MULTI_LOCALITY_LOCATION_METHOD,
    LocalityResolution,
    canonicalize_area_localities,
    combine_locality_resolutions,
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


def test_compound_servicetechniker_is_rejected_despite_method_evidence() -> None:
    decision = classify_job_candidate(
        _job(
            "Außendienst Servicetechniker Analytische Laborsysteme",
            "Inbetriebnahme, Wartung und technische Betreuung der Systeme vor Ort.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "service_technician" in decision.adjacent_title_matches
    assert "service_technician_trade" in decision.low_relevance_title_matches
    assert "commissioning" in decision.method_tool_matches


def test_service_technician_title_alone_is_not_enough() -> None:
    decision = classify_job_candidate(_job("Servicetechniker"))

    assert decision.accepted is False
    assert "service_technician" in decision.adjacent_title_matches
    assert "service_technician_trade" in decision.low_relevance_title_matches


def test_german_teamleitung_gets_team_lead_parity_in_technical_context() -> None:
    decision = classify_job_candidate(
        _job(
            "Teamleitung Arbeitsvorbereitung Zerspanung",
            "Arbeitsvorbereitung für Fertigung und Maschinenbau sowie technische Planung.",
        )
    )

    assert decision.accepted is True
    assert decision.reason == "engineering_role_with_domain"
    assert "team_lead" in decision.adjacent_title_matches
    assert "maschinenbau" in decision.domain_matches
    assert "manufacturing" in decision.domain_matches


def test_generic_teamleitung_is_not_promoted_without_engineering_evidence() -> None:
    decision = classify_job_candidate(
        _job(
            "Teamleitung HR Operations",
            "People management, recruiting and payroll administration.",
        )
    )

    assert decision.accepted is False
    assert "team_lead" in decision.adjacent_title_matches


def test_student_employee_strong_engineering_title_is_structurally_rejected() -> None:
    decision = classify_job_candidate(
        _job(
            "Student Employee Mechanical Engineer",
            "Mechanical design, CAD, FEM, prototypes and validation.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "mechanical_engineer" in decision.strong_title_matches
    assert "student_training_stage" in decision.low_relevance_title_matches


def test_working_student_engineering_title_is_structurally_rejected() -> None:
    decision = classify_job_candidate(
        _job(
            "Working Student Mechanical Engineer",
            "Mechanical design, CAD and testing.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "student_training_stage" in decision.low_relevance_title_matches


def test_real_engineering_intern_is_still_structurally_rejected() -> None:
    decision = classify_job_candidate(
        _job(
            "Mechanical Engineering Intern",
            "Mechanical engineering, CAD and testing.",
        )
    )

    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "student_training_stage" in decision.low_relevance_title_matches


def test_international_is_not_mistaken_for_internship_stage() -> None:
    decision = classify_job_candidate(
        _job(
            "Supervisor Mechanik - international",
            "Mechanical assembly and commissioning of machinery.",
        )
    )

    assert "student_training_stage" not in decision.low_relevance_title_matches
    assert decision.accepted is True


def test_internal_is_not_mistaken_for_internship_stage() -> None:
    decision = classify_job_candidate(_job("Internal Auditor", "Financial audit and controls."))

    assert "student_training_stage" not in decision.low_relevance_title_matches
    assert decision.accepted is False
    assert decision.reason == "insufficient_base_relevance"


def test_grossraum_label_extracts_only_explicit_named_localities() -> None:
    assert canonicalize_area_localities(
        "Großraum Linz, Steyr,Wels, Austria"
    ) == ("linz", "steyr", "wels")
    assert canonicalize_area_localities("Linz, Austria") == ()


def test_multi_locality_resolution_uses_equal_locality_centroid_and_provenance() -> None:
    resolution = combine_locality_resolutions(
        "Großraum Linz, Steyr,Wels, Austria",
        [
            LocalityResolution("Linz", "linz", 14.30, 48.30, ("4020",), 1000),
            LocalityResolution("Steyr", "steyr", 14.42, 48.04, ("4400",), 300),
            LocalityResolution("Wels", "wels", 14.03, 48.16, ("4600",), 500),
        ],
    )

    assert resolution is not None
    assert resolution.method == MULTI_LOCALITY_LOCATION_METHOD
    assert resolution.canonical_locality == "linz | steyr | wels"
    assert resolution.postal_codes == ("4020", "4400", "4600")
    assert resolution.address_sample_count == 1800
    assert round(resolution.longitude, 4) == 14.25
    assert round(resolution.latitude, 4) == 48.1667
