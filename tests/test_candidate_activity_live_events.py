from datetime import UTC, datetime
from types import SimpleNamespace

from app.candidate_activity import (
    CandidateJobView,
    CandidatePropertyPreference,
    mark_job_viewed,
    mark_property_viewed,
    set_property_favorite,
    set_property_hidden,
)
from app.live_events import LiveUiEvent


class StubSession:
    def __init__(self, *, scalar_result=None) -> None:
        self.scalar_result = scalar_result
        self.added: list[object] = []
        self.commits = 0

    def get(self, _model, _entity_id):
        return object()

    def scalar(self, _statement):
        return self.scalar_result

    def add(self, value) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1


def _events(session: StubSession) -> list[LiveUiEvent]:
    return [item for item in session.added if isinstance(item, LiveUiEvent)]


def test_property_favorite_publishes_house_curation_event() -> None:
    session = StubSession()
    profile = SimpleNamespace(id=7)

    set_property_favorite(session, profile, 41, favorite=True)

    events = _events(session)
    assert len(events) == 1
    assert events[0].topic == "houses"
    assert events[0].kind == "curation"
    assert events[0].entity_id == 41
    assert events[0].profile_id == 7
    assert events[0].payload == {"favorite": True, "hidden": False, "viewed": False}
    assert session.commits == 1


def test_property_hidden_publishes_house_curation_event() -> None:
    session = StubSession()
    profile = SimpleNamespace(id=7)

    set_property_hidden(session, profile, 42, hidden=True)

    events = _events(session)
    assert len(events) == 1
    assert events[0].topic == "houses"
    assert events[0].kind == "curation"
    assert events[0].entity_id == 42
    assert events[0].payload["hidden"] is True


def test_property_view_publishes_once_and_existing_view_does_not_repeat() -> None:
    profile = SimpleNamespace(id=7)
    fresh = StubSession()

    mark_property_viewed(fresh, profile, 43)

    events = _events(fresh)
    assert len(events) == 1
    assert events[0].topic == "houses"
    assert events[0].kind == "viewed"
    assert events[0].entity_id == 43
    assert events[0].payload["viewed"] is True

    viewed_at = datetime.now(UTC)
    existing = CandidatePropertyPreference(
        profile_id=7,
        property_id=43,
        favorite=False,
        hidden=False,
        viewed_at=viewed_at,
        created_at=viewed_at,
        updated_at=viewed_at,
    )
    repeated = StubSession(scalar_result=existing)

    mark_property_viewed(repeated, profile, 43)

    assert _events(repeated) == []
    assert repeated.commits == 1


def test_job_view_publishes_job_invalidation() -> None:
    session = StubSession()
    profile = SimpleNamespace(id=9)

    mark_job_viewed(session, profile, 77)

    assert any(isinstance(item, CandidateJobView) for item in session.added)
    events = _events(session)
    assert len(events) == 1
    assert events[0].topic == "jobs"
    assert events[0].kind == "viewed"
    assert events[0].entity_id == 77
    assert events[0].profile_id == 9
