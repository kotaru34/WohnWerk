from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import property_liveness
from app.database import SessionLocal
from app.models import ListingStatus, PropertyListing, Source

logger = logging.getLogger(__name__)

PROPERTY_PAGE_LIVENESS_POLICY = "visible-page-liveness-2026-08-29-v1"
PROPERTY_PAGE_LIVENESS_RECHECK_MINUTES = 30
PROPERTY_PAGE_LIVENESS_LIMIT = 72
_PROPERTY_CARD_RE = re.compile(rb'\bid="house-(\d+)"')
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()
_INFLIGHT_PROPERTY_IDS: set[int] = set()


def _parsed_checked_at(value: object | None) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _listing_checked_at(source_name: str, payload: dict) -> datetime | None:
    key = "source_liveness_checked_at" if source_name == "immmo.at" else "page_liveness_checked_at"
    return _parsed_checked_at(payload.get(key))


def _apply_direct_source_probe(
    listing: PropertyListing,
    probe: property_liveness.PropertyLivenessProbe,
) -> None:
    """Record page-level evidence without turning direct sources into IMMMO-policy rows."""
    payload = dict(listing.raw_payload or {})
    now = datetime.now(UTC)
    payload["page_liveness_policy"] = PROPERTY_PAGE_LIVENESS_POLICY
    payload["page_liveness_checked_at"] = now.isoformat()
    payload["page_liveness_state"] = probe.state
    payload["page_liveness_status_code"] = probe.status_code
    payload["page_liveness_reason"] = probe.reason
    payload["page_liveness_final_url"] = probe.final_url

    if probe.state == "live":
        payload["page_liveness_last_live_at"] = now.isoformat()
    elif probe.state == "dead":
        # A direct source gets hidden only on definitive dead evidence. Unknown/transient
        # responses leave the already-visible observation untouched. A future source crawl
        # may legitimately restore it if the board starts publishing the advert again.
        payload["product_visible"] = False
        payload["product_visibility_reason"] = "source_dead"

    listing.raw_payload = payload


async def refresh_visible_property_liveness(
    session: Session,
    property_ids: set[int],
    *,
    stale_minutes: int = PROPERTY_PAGE_LIVENESS_RECHECK_MINUTES,
    limit: int = PROPERTY_PAGE_LIVENESS_LIMIT,
) -> property_liveness.PropertyLivenessSummary:
    """Recheck stale source observations that were actually rendered to the user.

    The catalogue-wide worker stays conservative. Cards the user repeatedly sees receive a
    short freshness TTL. IMMMO observations retain the established downstream liveness
    policy; direct source rows such as s REAL use page-only evidence and are hidden only on
    a definitive dead result. Transient HTTP failures never remove a previously visible row.
    """
    if not property_ids:
        return property_liveness.PropertyLivenessSummary()

    original_missing = func.coalesce(
        PropertyListing.raw_payload.op("->>")("original_url_missing"),
        "false",
    )
    visible = PropertyListing.raw_payload["product_visible"].as_boolean()
    rows = list(
        session.execute(
            select(PropertyListing, Source.name)
            .join(Source, Source.id == PropertyListing.source_id)
            .where(
                PropertyListing.property_id.in_(property_ids),
                PropertyListing.status == ListingStatus.ACTIVE,
                PropertyListing.raw_payload.is_not(None),
                original_missing != "true",
                visible.is_(True),
            )
            .order_by(PropertyListing.id.asc())
        )
    )
    cutoff = datetime.now(UTC) - timedelta(minutes=max(1, stale_minutes))
    candidates: list[tuple[PropertyListing, str]] = []
    for listing, source_name in rows:
        checked_at = _listing_checked_at(source_name, listing.raw_payload or {})
        if checked_at is not None and checked_at > cutoff:
            continue
        candidates.append((listing, source_name))
        if len(candidates) >= max(1, limit):
            break

    if not candidates:
        return property_liveness.PropertyLivenessSummary()

    probes = await property_liveness.probe_property_urls(
        [listing.url for listing, _source_name in candidates]
    )
    counts = {"live": 0, "dead": 0, "unknown": 0}
    for listing, source_name in candidates:
        probe = probes[listing.url]
        counts[probe.state] += 1
        if source_name == "immmo.at":
            property_liveness._apply_persisted_probe(listing, probe)
        else:
            _apply_direct_source_probe(listing, probe)

    session.commit()
    return property_liveness.PropertyLivenessSummary(
        attempted=len(candidates),
        live=counts["live"],
        dead=counts["dead"],
        unknown=counts["unknown"],
    )


def refresh_property_page_liveness(property_ids: tuple[int, ...]) -> None:
    """Synchronous thread entry point used by the post-response task."""
    ids = {int(value) for value in property_ids if int(value) > 0}
    if not ids:
        return
    try:
        with SessionLocal() as session:
            result = asyncio.run(refresh_visible_property_liveness(session, ids))
        if result.attempted:
            logger.info(
                "visible property liveness: attempted=%d live=%d dead=%d unknown=%d",
                result.attempted,
                result.live,
                result.dead,
                result.unknown,
            )
    except Exception:
        # The response has already completed; a provider/network problem must never become
        # a user-facing catalogue error.
        logger.exception("visible property liveness refresh failed")


def _schedule_property_page_liveness(property_ids: tuple[int, ...]) -> None:
    pending = tuple(
        property_id
        for property_id in property_ids
        if property_id not in _INFLIGHT_PROPERTY_IDS
    )
    if not pending:
        return
    _INFLIGHT_PROPERTY_IDS.update(pending)

    async def run() -> None:
        try:
            await asyncio.to_thread(refresh_property_page_liveness, pending)
        finally:
            _INFLIGHT_PROPERTY_IDS.difference_update(pending)

    task = asyncio.create_task(run())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


class PropertyPageLivenessMiddleware:
    """Refresh only the property cards the user just saw, without delaying the response."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or scope.get("path") != "/houses":
            await self.app(scope, receive, send)
            return

        property_ids: set[int] = set()
        response_status = 0

        async def send_wrapper(message) -> None:
            nonlocal response_status
            if message.get("type") == "http.response.start":
                response_status = int(message.get("status") or 0)
            elif message.get("type") == "http.response.body" and 200 <= response_status < 300:
                body = message.get("body") or b""
                for match in _PROPERTY_CARD_RE.finditer(body):
                    property_ids.add(int(match.group(1)))
            await send(message)

        await self.app(scope, receive, send_wrapper)

        if property_ids and 200 <= response_status < 300:
            _schedule_property_page_liveness(tuple(sorted(property_ids)))
