import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.jobs.candidate_fit import CandidateJobPreference, CandidateProfile
from app.jobs.candidate_job_store import (
    load_candidate_job_states,
    merge_candidate_job_states,
    set_job_favorite,
    set_job_hidden,
)
from app.jobs.candidate_profile_seed import PROFILE_SLUG
from app.models import Job


def _database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Job.__table__.create(engine)
    CandidateProfile.__table__.create(engine)
    CandidateJobPreference.__table__.create(engine)
    return engine


def test_candidate_job_state_is_sparse_and_reversible() -> None:
    engine = _database()

    with Session(engine) as session:
        profile = CandidateProfile(slug=PROFILE_SLUG, label_de="Testprofil", enabled=True)
        job = Job(title="Mechanical Design Engineer", company="Beispiel GmbH")
        session.add_all([profile, job])
        session.commit()

        set_job_favorite(session, profile, job.id, favorite=True)
        state = load_candidate_job_states(session, profile.id, {job.id})[job.id]
        assert state.favorite is True
        assert state.hidden is False

        set_job_hidden(session, profile, job.id, hidden=True)
        state = load_candidate_job_states(session, profile.id, {job.id})[job.id]
        assert state.favorite is True
        assert state.hidden is True

        set_job_favorite(session, profile, job.id, favorite=False)
        state = load_candidate_job_states(session, profile.id, {job.id})[job.id]
        assert state.favorite is False
        assert state.hidden is True

        set_job_hidden(session, profile, job.id, hidden=False)
        assert load_candidate_job_states(session, profile.id, {job.id}) == {}
        assert session.scalar(select(CandidateJobPreference)) is None

        with pytest.raises(LookupError):
            set_job_favorite(session, profile, 999999, favorite=True)

    engine.dispose()


def test_candidate_job_state_survives_canonical_merge() -> None:
    engine = _database()

    with Session(engine) as session:
        profile = CandidateProfile(slug=PROFILE_SLUG, label_de="Testprofil", enabled=True)
        survivor = Job(title="Konstrukteur Maschinenbau", company="Beispiel GmbH")
        donor_a = Job(title="Konstrukteur Maschinenbau", company="Beispiel GmbH")
        donor_b = Job(title="Konstrukteur Maschinenbau", company="Beispiel GmbH")
        session.add_all([profile, survivor, donor_a, donor_b])
        session.flush()
        session.add_all(
            [
                CandidateJobPreference(
                    profile_id=profile.id,
                    job_id=donor_a.id,
                    favorite=True,
                    hidden=False,
                ),
                CandidateJobPreference(
                    profile_id=profile.id,
                    job_id=donor_b.id,
                    favorite=False,
                    hidden=True,
                ),
            ]
        )
        session.commit()

        merge_candidate_job_states(
            session,
            survivor_id=survivor.id,
            absorbed_ids=(donor_a.id, donor_b.id),
        )
        session.flush()

        rows = list(session.scalars(select(CandidateJobPreference)))
        assert len(rows) == 1
        assert rows[0].job_id == survivor.id
        assert rows[0].favorite is True
        assert rows[0].hidden is True

    engine.dispose()
