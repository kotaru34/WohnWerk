from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.jobs.candidate_fit import (
    CandidateConceptPreference,
    CandidatePreferenceSource,
    CandidatePreferenceState,
    CandidateProfile,
)
from app.jobs.candidate_profile_seed import PROFILE_PREFERENCES, PROFILE_SEED_VERSION
from app.jobs.concept_catalog import normalize_concept_text
from app.jobs.concepts import ConceptKind, JobConcept, JobConceptAlias, JobConceptEvidence


@dataclass(frozen=True, slots=True)
class ConceptAdminRow:
    concept: JobConcept
    preference: CandidateConceptPreference | None
    evidence_jobs: int
    evidence_primary: int
    evidence_context: int


def list_concepts_for_admin(
    session: Session,
    profile: CandidateProfile,
    *,
    kind: ConceptKind | None = None,
) -> list[ConceptAdminRow]:
    concept_stmt = select(JobConcept).options(selectinload(JobConcept.aliases))
    if kind is not None:
        concept_stmt = concept_stmt.where(JobConcept.kind == kind.value)
    concepts = list(session.scalars(concept_stmt.order_by(JobConcept.kind, JobConcept.label_de)))
    concept_ids = [concept.id for concept in concepts]

    preferences = {
        preference.concept_id: preference
        for preference in session.scalars(
            select(CandidateConceptPreference).where(
                CandidateConceptPreference.profile_id == profile.id,
                CandidateConceptPreference.concept_id.in_(concept_ids),
            )
        )
    } if concept_ids else {}

    counts: dict[int, tuple[int, int, int]] = {}
    if concept_ids:
        rows = session.execute(
            select(
                JobConceptEvidence.concept_id,
                func.count(func.distinct(JobConceptEvidence.job_id)),
                func.sum(case((JobConceptEvidence.scope == "primary", 1), else_=0)),
                func.sum(case((JobConceptEvidence.scope == "context", 1), else_=0)),
            )
            .where(JobConceptEvidence.concept_id.in_(concept_ids))
            .group_by(JobConceptEvidence.concept_id)
        )
        counts = {
            concept_id: (int(job_count or 0), int(primary or 0), int(context or 0))
            for concept_id, job_count, primary, context in rows
        }

    return [
        ConceptAdminRow(
            concept=concept,
            preference=preferences.get(concept.id),
            evidence_jobs=counts.get(concept.id, (0, 0, 0))[0],
            evidence_primary=counts.get(concept.id, (0, 0, 0))[1],
            evidence_context=counts.get(concept.id, (0, 0, 0))[2],
        )
        for concept in concepts
    ]


def set_manual_preference(
    session: Session,
    profile: CandidateProfile,
    concept_id: int,
    state: CandidatePreferenceState,
) -> None:
    concept = session.get(JobConcept, concept_id)
    if concept is None:
        raise LookupError("concept not found")

    preference = session.scalar(
        select(CandidateConceptPreference).where(
            CandidateConceptPreference.profile_id == profile.id,
            CandidateConceptPreference.concept_id == concept_id,
        )
    )
    if preference is None:
        preference = CandidateConceptPreference(
            profile_id=profile.id,
            concept_id=concept_id,
            state=state.value,
            source=CandidatePreferenceSource.MANUAL.value,
            seed_version=None,
        )
        session.add(preference)
    else:
        preference.state = state.value
        preference.source = CandidatePreferenceSource.MANUAL.value
        preference.seed_version = None
    session.commit()


def reset_preference_to_seed(
    session: Session,
    profile: CandidateProfile,
    concept_id: int,
) -> None:
    concept = session.get(JobConcept, concept_id)
    if concept is None:
        raise LookupError("concept not found")
    key = (ConceptKind(concept.kind), concept.slug)
    seed_state = PROFILE_PREFERENCES.get(key)
    preference = session.scalar(
        select(CandidateConceptPreference).where(
            CandidateConceptPreference.profile_id == profile.id,
            CandidateConceptPreference.concept_id == concept_id,
        )
    )

    if seed_state is None:
        if preference is not None:
            session.delete(preference)
    elif preference is None:
        session.add(
            CandidateConceptPreference(
                profile_id=profile.id,
                concept_id=concept_id,
                state=seed_state.value,
                source=CandidatePreferenceSource.SEED.value,
                seed_version=PROFILE_SEED_VERSION,
            )
        )
    else:
        preference.state = seed_state.value
        preference.source = CandidatePreferenceSource.SEED.value
        preference.seed_version = PROFILE_SEED_VERSION
    session.commit()


def add_manual_alias(
    session: Session,
    concept_id: int,
    alias_text: str,
    *,
    language: str | None = None,
) -> JobConceptAlias:
    concept = session.get(JobConcept, concept_id)
    if concept is None:
        raise LookupError("concept not found")
    alias_text = alias_text.strip()
    normalized = normalize_concept_text(alias_text)
    if not alias_text or not normalized:
        raise ValueError("alias must not be empty")

    existing = session.scalar(
        select(JobConceptAlias).where(
            JobConceptAlias.concept_id == concept_id,
            JobConceptAlias.normalized_alias == normalized,
        )
    )
    if existing is not None:
        existing.enabled = True
        session.commit()
        return existing

    alias = JobConceptAlias(
        concept_id=concept_id,
        alias=alias_text,
        normalized_alias=normalized,
        language=language.strip()[:8] if language and language.strip() else None,
        source="manual",
        enabled=True,
    )
    session.add(alias)
    session.commit()
    return alias


def set_alias_enabled(session: Session, alias_id: int, *, enabled: bool) -> None:
    alias = session.get(JobConceptAlias, alias_id)
    if alias is None:
        raise LookupError("alias not found")
    alias.enabled = enabled
    session.commit()


def delete_manual_alias(session: Session, alias_id: int) -> None:
    alias = session.get(JobConceptAlias, alias_id)
    if alias is None:
        raise LookupError("alias not found")
    if alias.source != "manual":
        raise ValueError("seed aliases cannot be deleted; disable them instead")
    session.execute(delete(JobConceptAlias).where(JobConceptAlias.id == alias_id))
    session.commit()
