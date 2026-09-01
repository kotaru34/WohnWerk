from types import SimpleNamespace

from app.live_ui import _event_data, _requested_cursor, _sse_frame


def test_last_event_id_wins_over_query_cursor() -> None:
    assert _requested_cursor(4, "9") == 9
    assert _requested_cursor(4, "not-a-number") == 4
    assert _requested_cursor(None, None) is None


def test_sse_frame_exposes_event_id_for_reconnect() -> None:
    frame = _sse_frame(event_id=12, event="invalidate", data='{"topic":"jobs"}')

    assert frame.startswith("id: 12\nevent: invalidate\n")
    assert 'data: {"topic":"jobs"}\n\n' in frame


def test_event_payload_contains_invalidation_scope() -> None:
    event = SimpleNamespace(
        topic="houses",
        kind="curation",
        entity_id=42,
        profile_id=3,
        payload={"favorite": True},
    )

    data = _event_data(event)

    assert '"topic":"houses"' in data
    assert '"kind":"curation"' in data
    assert '"entity_id":42' in data
    assert '"favorite":true' in data
