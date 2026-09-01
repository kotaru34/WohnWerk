from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.live_events import (
    LiveUiEvent,
    latest_live_event_id,
    live_events_after,
    queue_live_event,
)


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[LiveUiEvent.__table__])
    return Session(engine)


def test_live_event_model_resolves_profile_foreign_key_without_import_order_dependency() -> None:
    profile_fk = next(
        foreign_key
        for foreign_key in LiveUiEvent.__table__.foreign_keys
        if foreign_key.parent.name == "profile_id"
    )

    assert profile_fk.column.table.name == "candidate_profiles"
    assert profile_fk.column.name == "id"


def test_live_event_journal_orders_and_replays_after_cursor() -> None:
    with _session() as session:
        first = queue_live_event(
            session,
            topic="houses",
            kind="curation",
            entity_id=17,
            payload={"favorite": True},
        )
        second = queue_live_event(
            session,
            topic="jobs",
            kind="catalog_refresh",
            payload={"source": "example"},
        )
        session.commit()

        assert first.id == 1
        assert second.id == 2
        assert latest_live_event_id(session) == 2

        replay = live_events_after(session, 1)
        assert [event.id for event in replay] == [2]
        assert replay[0].topic == "jobs"
        assert replay[0].payload == {"source": "example"}


def test_live_event_rejects_unknown_topic() -> None:
    with _session() as session:
        try:
            queue_live_event(session, topic="other", kind="change")
        except ValueError as exc:
            assert "unsupported live UI topic" in str(exc)
        else:
            raise AssertionError("unknown topic was accepted")
