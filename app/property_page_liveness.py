from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, cast, func, or_, select
from sqlalchemy.orm import Session

from app import property_liveness
from app.database import SessionLocal
from app.models import ListingStatus, PropertyListing, Source

logger = logging.getLogger(__name__)

PROPERTY_PAGE_LIVENESS_RECHECK_MINUTES = 30
PROPERTY_PAGE_LIVENESS_LIMIT = 48
_PROPERTY_CARD_RE = re.compile(rb'\bid="house-(\d+)"')


async def refresh_visible_immmo_liveness(
    session: Session,
    property_ids: set[int],
    *,
    stale_minutes: int = PROPERTY_PAGE_LIVENESS_RECHECK_MINUTES,
    limit: int = PROPERTY_PAGE_LIVENESS_LIMIT,
) -> property_liveness.PropertyLivenessSummary:
    """Recheck stale IMMMO observations that were actually rendered to the user.

    This is intentionally separate from the catalogue-wide liveness sweep. The broad
    worker can stay conservative, while repeatedly viewed cards get a short freshness TTL.
    Only currently product-visible IMMMO observations are probed; transient failures retain
    the existing fail-safe semantics implemented by the main liveness policy.
    """
    if not property_ids:
        return property_liveness.PropertyLivenessSummary()

    source = session.scalar(select(Source).where(Source.name == "immmo.at"))
    if source is None:
        return property_liveness.PropertyLivenessSummary()

    checked_text = PropertyListing.raw_payload.op("->>")("source_liveness_checked_at")
    checked_at = cast(checked_text, DateTime(timezone=True))
    original_missing = func.coalesce(
        PropertyListing.raw_payload.op("->>")("original_url_missing"),
        "false",
    )
    visible = PropertyListing.raw_payload["product_visible"].as_boolean()
    cutoff = datetime.now(UTC) - timedelta(minutes=max(1, stale_minutes))

    listings = list(
        session.scalars(
            select(PropertyListing)
            .where(
                PropertyListing.source_id == source.id,
                PropertyListing.property_id.in_(property_ids),
                PropertyListing.status == ListingStatus.ACTIVE,
                PropertyListing.raw_payload.is_not(None),
                original_missing != "true",
                visible.is_(True),
                or_(checked_text.is_(None), checked_at <= cutoff),
            )
            .order_by(
                checked_at.asc().nullsfirst(),
                PropertyListing.id.asc(),
            )
            .limit(max(1, limit))
        )
    )
    if not listings:
        return property_liveness.PropertyLivenessSummary()

    probes = await property_liveness.probe_property_urls([listing.url for listing in listings])
    counts = {"live": 0, "dead": 0, "unknown": 0}
    for listing in listings:
        probe = probes[listing.url]
        counts[probe.state] += 1
        property_liveness._apply_persisted_probe(listing, probe)

    session.commit()
    return property_liveness.PropertyLivenessSummary(
        attempted=len(listings),
        live=counts["live"],
        dead=counts["dead"],
        unknown=counts["unknown"],
    )


def refresh_property_page_liveness(property_ids: tuple[int, ...]) -> None:
    """Synchronous thread entry point used after a /houses response has been sent."""
    ids = {int(value) for value in property_ids if int(value) > 0}
    if not ids:
        return
    try:
        with SessionLocal() as session:
            result = asyncio.run(refresh_visible_immmo_liveness(session, ids))
        if result.attempted:
            logger.info(
                "visible property liveness: attempted=%d live=%d dead=%d unknown=%d",
                result.attempted,
                result.live,
                result.dead,
                result.unknown,
            )
    except Exception:
        # Page rendering has already completed; a provider/network problem must never turn
        # a normal catalogue request into a user-facing error.
        logger.exception("visible property liveness refresh failed")


class PropertyPageLivenessMiddleware:
    """Tail-work middleware: refresh only the property cards the user just saw.

    The HTML response is sent normally. After it has been emitted, the request task waits
    for a thread that performs the stale-card check. From the browser's perspective this is
    non-blocking; a subsequent reload reflects any listing that was definitively found dead.
    """

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
            await asyncio.to_thread(
                refresh_property_page_liveness,
                tuple(sorted(property_ids)),
            )
