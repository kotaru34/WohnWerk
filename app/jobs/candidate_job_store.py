from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.candidate_fit import CandidateJobPreference, CandidateProfile
from app.live_events import queue_live_event
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
    changed = (current_favorite, current_hidden) != (next_favorite, next_hidden)

    if not next_favorite and not next_hidden:
        if row is not None:
            session.delete(row)
        if changed:
            queue_live_event(
                session,
                topic="jobs",
                kind="curation",
                entity_id=job_id,
                profile_id=profile.id,
                payload={"favorite": False, "hidden": False},
            )
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

    if changed:
        queue_live_event(
            session,
            topic="jobs",
            kind="curation",
            entity_id=job_id,
            profile_id=profile.id,
            payload={"favorite": next_favorite, "hidden": next_hidden},
        )
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


def merge_candidate_job_states(
    session: Session,
    *,
    survivor_id: int,
    absorbed_ids: tuple[int, ...],
) -> None:
    """Move sparse candidate curation onto a canonical merge survivor.

    Curation is conservative across duplicate identities: a favorite on any member remains
    a favorite, and a hidden marker on any member remains hidden. The helper deliberately
    does not commit so canonical merge and curation migration stay in one transaction.
    """

    job_ids = {survivor_id, *absorbed_ids}
    rows = list(
        session.scalars(
            select(CandidateJobPreference)
            .where(CandidateJobPreference.job_id.in_(job_ids))
            .order_by(CandidateJobPreference.profile_id, CandidateJobPreference.id)
        )
    )
    by_profile: dict[int, list[CandidateJobPreference]] = defaultdict(list)
    for row in rows:
        by_profile[row.profile_id].append(row)

    for profile_rows in by_profile.values():
        favorite = any(row.favorite for row in profile_rows)
        hidden = any(row.hidden for row in profile_rows)
        survivor_row = next((row for row in profile_rows if row.job_id == survivor_id), None)
        target = survivor_row or profile_rows[0]
        target.job_id = survivor_id
        target.favorite = favorite
        target.hidden = hidden
        for row in profile_rows:
            if row is not target:
                session.delete(row)
