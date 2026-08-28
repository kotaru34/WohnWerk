from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.candidate_fit import (
    CandidateConceptPreference,
    CandidatePreferenceSource,
    CandidatePreferenceState,
    CandidateProfile,
)
from app.jobs.candidate_profile_seed import (
    PROFILE_LABEL_DE,
    PROFILE_PREFERENCES,
    PROFILE_SEED_VERSION,
    PROFILE_SLUG,
)
from app.jobs.concepts import ConceptKind, JobConcept

ConceptKey = tuple[ConceptKind, str]
PreferenceMap = dict[ConceptKey, CandidatePreferenceState]


def enabled_concepts(session: Session) -> dict[ConceptKey, JobConcept]:
    return {
        (ConceptKind(concept.kind), concept.slug): concept
        for concept in session.scalars(
            select(JobConcept).where(JobConcept.enabled.is_(True)).order_by(JobConcept.id)
        )
    }


def get_profile(session: Session, slug: str) -> CandidateProfile | None:
    return session.scalar(select(CandidateProfile).where(CandidateProfile.slug == slug))


def get_seed_profile(session: Session) -> CandidateProfile | None:
    return get_profile(session, PROFILE_SLUG)


def preference_rows(
    session: Session,
    profile_id: int,
) -> list[tuple[CandidateConceptPreference, JobConcept]]:
    return list(
        session.execute(
            select(CandidateConceptPreference, JobConcept)
            .join(JobConcept, JobConcept.id == CandidateConceptPreference.concept_id)
            .where(CandidateConceptPreference.profile_id == profile_id)
            .order_by(JobConcept.kind, JobConcept.slug)
        ).all()
    )


def concept_key(concept: JobConcept) -> ConceptKey:
    return ConceptKind(concept.kind), concept.slug


def format_concept_keys(keys: list[ConceptKey]) -> str:
    return ",".join(f"{kind.value}:{slug}" for kind, slug in sorted(keys)) or "-"


def load_profile_preferences(session: Session, slug: str = PROFILE_SLUG) -> PreferenceMap:
    """Load the persisted source-of-truth preference map for one enabled profile."""

    profile = get_profile(session, slug)
    if profile is None:
        raise ValueError(f"candidate profile does not exist: {slug}")
    if not profile.enabled:
        raise ValueError(f"candidate profile is disabled: {slug}")

    result: PreferenceMap = {}
    for preference, concept in preference_rows(session, profile.id):
        if not concept.enabled:
            continue
        result[concept_key(concept)] = CandidatePreferenceState(preference.state)
    return result


def sync_seed_profile(session: Session) -> CandidateProfile:
    """Synchronize seed-managed preferences while preserving every manual override.

    Existing rows with source=seed may follow a newer profile seed. Rows with source=manual
    are never changed. Seed-managed rows removed from the current seed are deleted so a seed
    can intentionally stop making a claim without affecting manual preferences.
    """

    concepts = enabled_concepts(session)
    missing_concepts = [key for key in PROFILE_PREFERENCES if key not in concepts]
    if missing_concepts:
        raise ValueError(
            "cannot seed candidate profile; missing enabled concepts: "
            + format_concept_keys(missing_concepts)
        )

    profile = get_seed_profile(session)
    if profile is None:
        profile = CandidateProfile(slug=PROFILE_SLUG, label_de=PROFILE_LABEL_DE, enabled=True)
        session.add(profile)
        session.flush()

    rows = preference_rows(session, profile.id)
    by_key = {concept_key(concept): preference for preference, concept in rows}

    for key, expected_state in PROFILE_PREFERENCES.items():
        preference = by_key.get(key)
        if preference is None:
            session.add(
                CandidateConceptPreference(
                    profile_id=profile.id,
                    concept_id=concepts[key].id,
                    state=expected_state.value,
                    source=CandidatePreferenceSource.SEED.value,
                    seed_version=PROFILE_SEED_VERSION,
                )
            )
            continue

        if preference.source != CandidatePreferenceSource.SEED.value:
            continue
        preference.state = expected_state.value
        preference.seed_version = PROFILE_SEED_VERSION

    for preference, concept in rows:
        if (
            preference.source == CandidatePreferenceSource.SEED.value
            and concept_key(concept) not in PROFILE_PREFERENCES
        ):
            session.delete(preference)

    session.commit()
    return profile
