from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base


class LiveUiEvent(Base):
    __tablename__ = "live_ui_events"
    __table_args__ = (
        Index("ix_live_ui_events_topic_id", "topic", "id"),
        Index("ix_live_ui_events_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )


def queue_live_event(
    session: Session,
    *,
    topic: str,
    kind: str,
    entity_id: int | None = None,
    profile_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> LiveUiEvent:
    """Queue an invalidation event in the caller's current transaction.

    The helper deliberately does not commit. Domain state and its UI invalidation therefore
    become visible atomically when the caller commits its normal write transaction.
    """
    if topic not in {"houses", "jobs", "all"}:
        raise ValueError(f"unsupported live UI topic: {topic}")
    normalized_kind = kind.strip()
    if not normalized_kind:
        raise ValueError("live UI event kind must not be empty")

    event = LiveUiEvent(
        topic=topic,
        kind=normalized_kind,
        entity_id=entity_id,
        profile_id=profile_id,
        payload=dict(payload or {}),
    )
    session.add(event)
    return event


def latest_live_event_id(session: Session) -> int:
    return int(session.scalar(select(func.max(LiveUiEvent.id))) or 0)


def live_events_after(
    session: Session,
    event_id: int,
    *,
    limit: int = 100,
) -> list[LiveUiEvent]:
    bounded_limit = max(1, min(int(limit), 500))
    return list(
        session.scalars(
            select(LiveUiEvent)
            .where(LiveUiEvent.id > max(0, int(event_id)))
            .order_by(LiveUiEvent.id)
            .limit(bounded_limit)
        )
    )
