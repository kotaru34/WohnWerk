import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.jobs.candidate_fit import CandidateJobPreference, CandidateProfile
from app.jobs.candidate_job_store import (
    load_candidate_job_states,
    set_job_favorite,
    set_job_hidden,
)
from app.jobs.candidate_profile_seed import PROFILE_SLUG
from app.models import Job


def test_candidate_job_state_is_sparse_and_reversible() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Job.__table__.create(engine)
    CandidateProfile.__table__.create(engine)
    CandidateJobPreference.__table__.create(engine)

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
