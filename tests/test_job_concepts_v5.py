from app.jobs.candidate_profile_seed import PROFILE_PREFERENCES
from app.jobs.concept_catalog import EXTRACTOR_VERSION, JobTextSnapshot, extract_concepts
from app.jobs.concepts import ConceptKind


def _slugs(title: str, description: str | None = None) -> set[tuple[str, str]]:
    return {
        (match.kind.value, match.slug)
        for match in extract_concepts(
            JobTextSnapshot(job_id=374, title=title, description=description)
        )
    }


def test_v5_version_is_explicit() -> None:
    assert EXTRACTOR_VERSION == "concept-seed-2026-09-01-v5"


def test_mechanical_fluids_engineer_maps_to_existing_mechanical_engineer_role() -> None:
    slugs = _slugs("Mechanical/Fluids Engineer")

    assert ("role", "mechanical-engineer") in slugs


def test_plain_fluids_engineer_does_not_invent_mechanical_role() -> None:
    slugs = _slugs("Fluids Engineer")

    assert ("role", "mechanical-engineer") not in slugs


def test_v5_does_not_change_candidate_profile_preferences() -> None:
    assert (
        PROFILE_PREFERENCES[ConceptKind.ROLE, "mechanical-engineer"]
        .value
        == "can_want"
    )
