from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.candidate_fit import CandidateJobPreference, CandidateProfile
from app.models import Job


@dataclass(frozen=True, slots=True)
class CandidateJobState:
    favorite: bool = False
    hidden: bool = False


def load_candidate_job_states(
    session: Session,
    profile_id: int,
    job_ids: set[int],
) -> dict[int, CandidateJobState]:
    if not job_ids:
        return {}
    rows = session.scalars(
        select(CandidateJobPreference).where(
            CandidateJobPreference.profile_id == profile_id,
            CandidateJobPreference.job_id.in_(job_ids),
        )
    )
    return {
        row.job_id: CandidateJobState(favorite=row.favorite, hidden=row.hidden) for row in rows
    }


def _preference_row(
    session: Session,
    profile: CandidateProfile,
    job_id: int,
) -> CandidateJobPreference | None:
    return session.scalar(
        select(CandidateJobPreference).where(
            CandidateJobPreference.profile_id == profile.id,
            CandidateJobPreference.job_id == job_id,
        )
    )


def _ensure_job(session: Session, job_id: int) -> None:
    if session.get(Job, job_id) is None:
        raise LookupError("job not found")


def _save_sparse_state(
    session: Session,
    profile: CandidateProfile,
    job_id: int,
    *,
    favorite: bool | None = None,
    hidden: bool | None = None,
) -> None:
    _ensure_job(session, job_id)
    row = _preference_row(session, profile, job_id)
    current_favorite = row.favorite if row is not None else False
    current_hidden = row.hidden if row is not None else False
    next_favorite = current_favorite if favorite is None else favorite
    next_hidden = current_hidden if hidden is None else hidden

    if not next_favorite and not next_hidden:
        if row is not None:
            session.delete(row)
        session.commit()
        return

    if row is None:
        row = CandidateJobPreference(
            profile_id=profile.id,
            job_id=job_id,
            favorite=next_favorite,
            hidden=next_hidden,
        )
        session.add(row)
    else:
        row.favorite = next_favorite
        row.hidden = next_hidden
    session.commit()


def set_job_favorite(
    session: Session,
    profile: CandidateProfile,
    job_id: int,
    *,
    favorite: bool,
) -> None:
    _save_sparse_state(session, profile, job_id, favorite=favorite)


def set_job_hidden(
    session: Session,
    profile: CandidateProfile,
    job_id: int,
    *,
    hidden: bool,
) -> None:
    _save_sparse_state(session, profile, job_id, hidden=hidden)
