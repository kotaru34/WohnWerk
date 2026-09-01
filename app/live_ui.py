from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.admin import AdminDependency
from app.database import SessionLocal
from app.live_events import latest_live_event_id, live_events_after

router = APIRouter(tags=["site"])

_POLL_SECONDS = 1.0
_KEEPALIVE_SECONDS = 15.0
_BATCH_SIZE = 100


def _event_data(event) -> str:
    return json.dumps(
        {
            "topic": event.topic,
            "kind": event.kind,
            "entity_id": event.entity_id,
            "profile_id": event.profile_id,
            "payload": event.payload or {},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _sse_frame(*, event_id: int, event: str, data: str) -> str:
    lines = [f"id: {event_id}", f"event: {event}"]
    lines.extend(f"data: {line}" for line in data.splitlines() or [""])
    return "\n".join(lines) + "\n\n"


def _requested_cursor(after: int | None, last_event_id: str | None) -> int | None:
    if last_event_id:
        try:
            value = int(last_event_id)
        except ValueError:
            pass
        else:
            return max(0, value)
    return after


async def _stream_events(request: Request, *, initial_cursor: int | None) -> AsyncIterator[str]:
    with SessionLocal() as session:
        high_water = latest_live_event_id(session)

    cursor = high_water if initial_cursor is None else min(max(0, initial_cursor), high_water)
    yield _sse_frame(
        event_id=cursor,
        event="ready",
        data=json.dumps({"cursor": cursor}, separators=(",", ":")),
    )

    quiet_seconds = 0.0
    while not await request.is_disconnected():
        with SessionLocal() as session:
            events = live_events_after(session, cursor, limit=_BATCH_SIZE)

        if events:
            for event in events:
                cursor = event.id
                yield _sse_frame(
                    event_id=event.id,
                    event="invalidate",
                    data=_event_data(event),
                )
            quiet_seconds = 0.0
            continue

        await asyncio.sleep(_POLL_SECONDS)
        quiet_seconds += _POLL_SECONDS
        if quiet_seconds >= _KEEPALIVE_SECONDS:
            yield f": keepalive {cursor}\n\n"
            quiet_seconds = 0.0


@router.get("/events", include_in_schema=False)
async def live_events_stream(
    request: Request,
    _: AdminDependency,
    after: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
):
    cursor = _requested_cursor(after, last_event_id)
    return StreamingResponse(
        _stream_events(request, initial_cursor=cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )
