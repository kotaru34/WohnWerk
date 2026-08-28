from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.jobs.candidate_fit import (
    CandidateConceptPreference,
    CandidatePreferenceSource,
    CandidatePreferenceState,
    CandidateProfile,
)
from app.jobs.candidate_profile_seed import PROFILE_PREFERENCES, PROFILE_SEED_VERSION, PROFILE_SLUG
from app.jobs.concepts import JobConcept
from scripts.sync_candidate_profile import _apply


def _database() -> tuple[object, Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    JobConcept.__table__.create(engine)
    CandidateProfile.__table__.create(engine)
    CandidateConceptPreference.__table__.create(engine)
    return engine, Session(engine)


def _seed_required_concepts(session: Session) -> None:
    for kind, slug in PROFILE_PREFERENCES:
        session.add(
            JobConcept(
                kind=kind.value,
                slug=slug,
                label_de=slug,
                enabled=True,
            )
        )
    session.commit()


def test_profile_seed_is_idempotent_and_preserves_manual_override() -> None:
    engine, session = _database()
    try:
        _seed_required_concepts(session)

        _apply(session)
        profile = session.scalar(select(CandidateProfile).where(CandidateProfile.slug == PROFILE_SLUG))
        assert profile is not None
        preferences = list(
            session.scalars(
                select(CandidateConceptPreference).where(
                    CandidateConceptPreference.profile_id == profile.id
                )
            )
        )
        assert len(preferences) == len(PROFILE_PREFERENCES) == 24
        assert {item.source for item in preferences} == {CandidatePreferenceSource.SEED.value}
        assert {item.seed_version for item in preferences} == {PROFILE_SEED_VERSION}

        manual = preferences[0]
        manual.source = CandidatePreferenceSource.MANUAL.value
        manual.seed_version = None
        original_seed_state = manual.state
        manual.state = (
            CandidatePreferenceState.CANNOT_NOT_WANT.value
            if original_seed_state != CandidatePreferenceState.CANNOT_NOT_WANT.value
            else CandidatePreferenceState.CAN_WANT.value
        )
        manual_state = manual.state
        session.commit()

        _apply(session)
        session.refresh(manual)
        assert manual.source == CandidatePreferenceSource.MANUAL.value
        assert manual.seed_version is None
        assert manual.state == manual_state

        preferences_after = list(
            session.scalars(
                select(CandidateConceptPreference).where(
                    CandidateConceptPreference.profile_id == profile.id
                )
            )
        )
        assert len(preferences_after) == len(PROFILE_PREFERENCES)
    finally:
        session.close()
        engine.dispose()
