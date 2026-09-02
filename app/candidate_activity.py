from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, UniqueConstraint, exists, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base
from app.jobs.candidate_fit import CandidateProfile
from app.live_events import queue_live_event
from app.models import Job, Property


class CandidateNoveltyBaseline(Base):
    __tablename__ = "candidate_novelty_baselines"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CandidateJobView(Base):
    __tablename__ = "candidate_job_views"
    __table_args__ = (
        UniqueConstraint("profile_id", "job_id", name="uq_candidate_job_view_profile_job"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CandidatePropertyPreference(Base):
    __tablename__ = "candidate_property_preferences"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "property_id",
            name="uq_candidate_property_preference_profile_property",
        ),
        Index("ix_candidate_property_preferences_profile_hidden", "profile_id", "hidden"),
        Index("ix_candidate_property_preferences_profile_favorite", "profile_id", "favorite"),
        Index("ix_candidate_property_preferences_profile_viewed", "profile_id", "viewed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), index=True, nullable=False
    )
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True, slots=True)
class CandidatePropertyState:
    favorite: bool = False
    hidden: bool = False
    viewed_at: datetime | None = None

    @property
    def viewed(self) -> bool:
        return self.viewed_at is not None


def novelty_baseline(session: Session, profile: CandidateProfile) -> datetime:
    row = session.scalar(
        select(CandidateNoveltyBaseline).where(
            CandidateNoveltyBaseline.profile_id == profile.id
        )
    )
    if row is not None:
        return row.started_at

    now = datetime.now(UTC)
    session.add(CandidateNoveltyBaseline(profile_id=profile.id, started_at=now))
    session.commit()
    return now


def load_job_viewed_ids(
    session: Session,
    profile_id: int,
    job_ids: set[int],
) -> set[int]:
    if not job_ids:
        return set()
    return set(
        session.scalars(
            select(CandidateJobView.job_id).where(
                CandidateJobView.profile_id == profile_id,
                CandidateJobView.job_id.in_(job_ids),
            )
        )
    )


def mark_job_viewed(session: Session, profile: CandidateProfile, job_id: int) -> None:
    if session.get(Job, job_id) is None:
        raise LookupError("job not found")
    existing = session.scalar(
        select(CandidateJobView).where(
            CandidateJobView.profile_id == profile.id,
            CandidateJobView.job_id == job_id,
        )
    )
    if existing is None:
        session.add(
            CandidateJobView(
                profile_id=profile.id,
                job_id=job_id,
                viewed_at=datetime.now(UTC),
            )
        )
        queue_live_event(
            session,
            topic="jobs",
            kind="viewed",
            entity_id=job_id,
            profile_id=profile.id,
        )
        session.commit()


def load_property_states(
    session: Session,
    profile_id: int,
    property_ids: set[int],
) -> dict[int, CandidatePropertyState]:
    if not property_ids:
        return {}
    rows = session.scalars(
        select(CandidatePropertyPreference).where(
            CandidatePropertyPreference.profile_id == profile_id,
            CandidatePropertyPreference.property_id.in_(property_ids),
        )
    )
    return {
        row.property_id: CandidatePropertyState(
            favorite=row.favorite,
            hidden=row.hidden,
            viewed_at=row.viewed_at,
        )
        for row in rows
    }


def property_curation_condition(profile_id: int, view: str):
    hidden = exists(
        select(CandidatePropertyPreference.id).where(
            CandidatePropertyPreference.profile_id == profile_id,
            CandidatePropertyPreference.property_id == Property.id,
            CandidatePropertyPreference.hidden.is_(True),
        )
    )
    if view == "ausgeblendet":
        return hidden
    if view == "favoriten":
        return exists(
            select(CandidatePropertyPreference.id).where(
                CandidatePropertyPreference.profile_id == profile_id,
                CandidatePropertyPreference.property_id == Property.id,
                CandidatePropertyPreference.favorite.is_(True),
            )
        )
    return ~hidden


def hidden_property_ids(session: Session, profile_id: int) -> set[int]:
    return set(
        session.scalars(
            select(CandidatePropertyPreference.property_id).where(
                CandidatePropertyPreference.profile_id == profile_id,
                CandidatePropertyPreference.hidden.is_(True),
            )
        )
    )


def _property_preference_row(
    session: Session,
    profile: CandidateProfile,
    property_id: int,
) -> CandidatePropertyPreference | None:
    return session.scalar(
        select(CandidatePropertyPreference).where(
            CandidatePropertyPreference.profile_id == profile.id,
            CandidatePropertyPreference.property_id == property_id,
        )
    )


def _ensure_property(session: Session, property_id: int) -> None:
    if session.get(Property, property_id) is None:
        raise LookupError("property not found")


def _save_property_state(
    session: Session,
    profile: CandidateProfile,
    property_id: int,
    *,
    favorite: bool | None = None,
    hidden: bool | None = None,
    mark_viewed: bool = False,
) -> None:
    _ensure_property(session, property_id)
    row = _property_preference_row(session, profile, property_id)
    now = datetime.now(UTC)

    current_favorite = row.favorite if row is not None else False
    current_hidden = row.hidden if row is not None else False
    current_viewed = row.viewed_at if row is not None else None
    next_favorite = current_favorite if favorite is None else favorite
    next_hidden = current_hidden if hidden is None else hidden
    next_viewed = now if mark_viewed and current_viewed is None else current_viewed
    changed = (current_favorite, current_hidden, current_viewed) != (
        next_favorite,
        next_hidden,
        next_viewed,
    )

    if row is None:
        row = CandidatePropertyPreference(
            profile_id=profile.id,
            property_id=property_id,
            favorite=next_favorite,
            hidden=next_hidden,
            viewed_at=next_viewed,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.favorite = next_favorite
        row.hidden = next_hidden
        row.viewed_at = next_viewed
        row.updated_at = now

    if changed:
        queue_live_event(
            session,
            topic="houses",
            kind="viewed" if mark_viewed and current_viewed is None else "curation",
            entity_id=property_id,
            profile_id=profile.id,
            payload={
                "favorite": next_favorite,
                "hidden": next_hidden,
                "viewed": next_viewed is not None,
            },
        )
    session.commit()


def set_property_favorite(
    session: Session,
    profile: CandidateProfile,
    property_id: int,
    *,
    favorite: bool,
) -> None:
    _save_property_state(session, profile, property_id, favorite=favorite)


def set_property_hidden(
    session: Session,
    profile: CandidateProfile,
    property_id: int,
    *,
    hidden: bool,
) -> None:
    _save_property_state(session, profile, property_id, hidden=hidden)


def mark_property_viewed(
    session: Session,
    profile: CandidateProfile,
    property_id: int,
) -> None:
    _save_property_state(session, profile, property_id, mark_viewed=True)


def is_new_unviewed(
    *,
    first_seen_at: datetime,
    baseline: datetime,
    viewed_at: datetime | None,
) -> bool:
    return viewed_at is None and first_seen_at > baseline
