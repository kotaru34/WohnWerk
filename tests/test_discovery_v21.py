from app.jobs.discovery import DISCOVERY_GATE_VERSION, classify_job_candidate
from app.sources.base import RawJob, RawJobLocation


def _job(title: str, description: str | None = None) -> RawJob:
    return RawJob(
        source_listing_id=title,
        url="https://example.invalid/successfactors/job",
        title=title,
        description=description,
        locations=[RawJobLocation(city="Weiz", location_text="Weiz, Styria, AT")],
    )


def test_v21_rejects_live_andritz_commercial_project_manager() -> None:
    decision = classify_job_candidate(
        _job(
            "Commercial Project Manager (m/w/d)",
            (
                "Kaufmännische Ausbildung und mehrjährige kaufmännische Berufserfahrung. "
                "Kaufmännische Auftragsabwicklung, Vertragsmanagement, Kostencontrolling, "
                "Project Cash Flow Management, Risiko- und Claimmanagement für Hydropower."
            ),
        )
    )

    assert DISCOVERY_GATE_VERSION == "profile-seed-2026-08-30-v21"
    assert decision.accepted is False
    assert decision.reason == "structural_title_exclusion"
    assert "commercial_project_management" in decision.low_relevance_title_matches


def test_v21_keeps_real_industrial_project_manager() -> None:
    decision = classify_job_candidate(
        _job(
            "Project Manager / System Engineer Generator (m/w/d)",
            (
                "Technische Ausbildung vorzugsweise Maschinenbau und Berufserfahrung "
                "im Projektgeschäft für Generatoren. Koordination der technischen "
                "Auftragsabwicklung und Schnittstellen."
            ),
        )
    )

    assert decision.accepted is True
    assert decision.reason == "industrial_project_title"
