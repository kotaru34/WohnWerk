from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import DateTime, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models import ListingStatus, PropertyListing, Source
from app.property_acquisition import property_budget_decision
from app.property_images import _safe_http_url
from app.sources.base import RawProperty

PROPERTY_LIVENESS_POLICY = "immmo-external-liveness-2026-08-29-v1"
PROPERTY_LIVENESS_TIMEOUT_SECONDS = 8.0
PROPERTY_LIVENESS_BODY_LIMIT_BYTES = 512 * 1024
PROPERTY_LIVENESS_CONCURRENCY = 12
PROPERTY_LIVENESS_WORKER_LIMIT = 120
PROPERTY_LIVENESS_RECHECK_HOURS = 24 * 7

_LIVENESS_PAYLOAD_KEYS = (
    "source_liveness_policy",
    "source_liveness_required",
    "source_liveness_state",
    "source_liveness_checked_at",
    "source_liveness_status_code",
    "source_liveness_reason",
    "source_liveness_final_url",
    "source_liveness_last_live_at",
)

_CLOSED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "dibeo_already_found",
        re.compile(r"\bdiese\s+immobilie\s+wurde\s+schon\s+gefunden\b", re.IGNORECASE),
    ),
    (
        "property_no_longer_available",
        re.compile(
            r"\b(?:diese[sr]?\s+)?(?:immobilie|objekt|inserat|anzeige|angebot|expos(?:é|e))"
            r"[^.]{0,80}\bnicht\s+mehr\s+verf(?:ü|ue)gbar\b",
            re.IGNORECASE,
        ),
    ),
    (
        "listing_deactivated",
        re.compile(
            r"\b(?:inserat|anzeige|expos(?:é|e)|objekt)\w*[^.]{0,60}"
            r"\b(?:deaktiviert|gel(?:ö|oe)scht|entfernt)\b",
            re.IGNORECASE,
        ),
    ),
)

_ANTIBOT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("captcha", re.compile(r"\bcaptcha\b", re.IGNORECASE)),
    ("cloudflare_challenge", re.compile(r"\bjust\s+a\s+moment\b", re.IGNORECASE)),
    ("access_denied", re.compile(r"\baccess\s+denied\b", re.IGNORECASE)),
)


@dataclass(frozen=True, slots=True)
class PropertyLivenessProbe:
    state: str
    status_code: int | None
    reason: str
    final_url: str | None = None


@dataclass(frozen=True, slots=True)
class PropertyLivenessSummary:
    attempted: int = 0
    live: int = 0
    dead: int = 0
    unknown: int = 0


def assess_property_page(status_code: int | None, body: str | None) -> tuple[str, str]:
    """Classify downstream property pages conservatively.

    Explicit 404/410 or provider removal text is authoritative dead evidence. Anti-bot,
    rate-limit and server errors are unknown rather than dead so transient provider behavior
    cannot hide previously-good listings.
    """
    if status_code is None:
        return "unknown", "request_failed"
    if status_code in {404, 410}:
        return "dead", f"http_{status_code}"

    text = body or ""
    for name, pattern in _CLOSED_PATTERNS:
        if pattern.search(text):
            return "dead", name
    for name, pattern in _ANTIBOT_PATTERNS:
        if pattern.search(text):
            return "unknown", name

    if 200 <= status_code < 400:
        return "live", "http_live"
    if status_code in {401, 403, 429} or status_code >= 500:
        return "unknown", f"http_{status_code}"
    return "unknown", f"http_{status_code}"


def _decode_body(content: bytes, encoding: str | None) -> str:
    codec = encoding or "utf-8"
    try:
        return content.decode(codec, errors="replace")
    except LookupError:
        return content.decode("utf-8", errors="replace")


async def _probe_one(
    client: httpx.AsyncClient,
    url: str,
    semaphore: asyncio.Semaphore,
    *,
    body_limit: int,
) -> PropertyLivenessProbe:
    safe = _safe_http_url(url)
    if safe is None:
        return PropertyLivenessProbe("dead", None, "unsafe_or_missing_url")

    try:
        async with semaphore, client.stream("GET", safe) as response:
            final_url = _safe_http_url(str(response.url))
            if final_url is None:
                return PropertyLivenessProbe(
                    "unknown",
                    response.status_code,
                    "unsafe_redirect",
                    str(response.url),
                )

            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                if total >= body_limit:
                    break
                remaining = body_limit - total
                chunks.append(chunk[:remaining])
                total += min(len(chunk), remaining)
                if total >= body_limit:
                    break
            body = _decode_body(b"".join(chunks), response.encoding)
            state, reason = assess_property_page(response.status_code, body)
            return PropertyLivenessProbe(state, response.status_code, reason, final_url)
    except httpx.HTTPError as exc:
        return PropertyLivenessProbe(
            "unknown",
            None,
            f"{type(exc).__name__}: {exc}"[:300],
        )


async def probe_property_urls(urls: list[str]) -> dict[str, PropertyLivenessProbe]:
    if not urls:
        return {}
    headers = {
        "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian property search; liveness)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
    }
    semaphore = asyncio.Semaphore(PROPERTY_LIVENESS_CONCURRENCY)
    unique_urls = list(dict.fromkeys(urls))
    async with httpx.AsyncClient(
        headers=headers,
        timeout=PROPERTY_LIVENESS_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(
            *(
                _probe_one(
                    client,
                    url,
                    semaphore,
                    body_limit=PROPERTY_LIVENESS_BODY_LIMIT_BYTES,
                )
                for url in unique_urls
            )
        )
    return dict(zip(unique_urls, results, strict=True))


def _copy_liveness_payload(source_payload: dict | None, target_payload: dict) -> None:
    source_payload = source_payload or {}
    for key in _LIVENESS_PAYLOAD_KEYS:
        if key in source_payload:
            target_payload[key] = source_payload[key]


def _apply_probe(payload: dict, probe: PropertyLivenessProbe, *, new_listing: bool) -> dict:
    now = datetime.now(UTC)
    updated = dict(payload)
    updated["source_liveness_policy"] = PROPERTY_LIVENESS_POLICY
    updated["source_liveness_state"] = probe.state
    updated["source_liveness_checked_at"] = now.isoformat()
    updated["source_liveness_status_code"] = probe.status_code
    updated["source_liveness_reason"] = probe.reason
    updated["source_liveness_final_url"] = probe.final_url

    if probe.state == "live":
        updated["source_liveness_required"] = True
        updated["source_liveness_last_live_at"] = now.isoformat()
    elif probe.state == "dead":
        updated["source_liveness_required"] = True
    elif new_listing:
        # A new meta-search result must earn product visibility. Unknown/anti-bot evidence
        # therefore stays fail-closed and can be retried by the background worker.
        updated["source_liveness_required"] = True
    # Existing grandfathered listings remain visible on transient unknown evidence. They
    # become policy-controlled only after a definitive live/dead probe.
    return updated


async def prepare_immmo_item_liveness(
    session: Session,
    source: Source,
    items: list[RawProperty],
) -> PropertyLivenessSummary:
    """Carry forward liveness state and probe only genuinely new product-eligible URLs."""
    if source.name != "immmo.at" or not items:
        return PropertyLivenessSummary()

    source_ids = [item.source_listing_id for item in items]
    existing = {
        listing.source_listing_id: listing
        for listing in session.scalars(
            select(PropertyListing).where(
                PropertyListing.source_id == source.id,
                PropertyListing.source_listing_id.in_(source_ids),
            )
        )
    }

    pending: list[RawProperty] = []
    for item in items:
        payload = dict(item.raw_payload)
        previous = existing.get(item.source_listing_id)
        if previous is not None:
            _copy_liveness_payload(previous.raw_payload, payload)
            item.raw_payload = payload
            continue

        if payload.get("original_url_missing") is True:
            item.raw_payload = payload
            continue
        if not property_budget_decision(item.price_eur).accepted:
            item.raw_payload = payload
            continue

        payload["source_liveness_policy"] = PROPERTY_LIVENESS_POLICY
        payload["source_liveness_required"] = True
        payload["source_liveness_state"] = "unverified"
        item.raw_payload = payload
        pending.append(item)

    probes = await probe_property_urls([item.url for item in pending])
    counts = {"live": 0, "dead": 0, "unknown": 0}
    for item in pending:
        probe = probes[item.url]
        counts[probe.state] += 1
        item.raw_payload = _apply_probe(item.raw_payload, probe, new_listing=True)

    return PropertyLivenessSummary(
        attempted=len(pending),
        live=counts["live"],
        dead=counts["dead"],
        unknown=counts["unknown"],
    )


def _payload_price(payload: dict) -> Decimal | None:
    value = payload.get("source_price_eur")
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _apply_persisted_probe(listing: PropertyListing, probe: PropertyLivenessProbe) -> None:
    payload = _apply_probe(
        dict(listing.raw_payload or {}),
        probe,
        new_listing=(listing.raw_payload or {}).get("source_liveness_required") is True,
    )
    decision = property_budget_decision(_payload_price(payload))
    if not decision.accepted:
        payload["product_visible"] = False
        payload["product_visibility_reason"] = decision.reason
    elif payload.get("original_url_missing") is True:
        payload["product_visible"] = False
        payload["product_visibility_reason"] = "source_url_missing"
    elif probe.state == "live":
        payload["product_visible"] = True
        payload["product_visibility_reason"] = "accepted"
    elif probe.state == "dead":
        payload["product_visible"] = False
        payload["product_visibility_reason"] = "source_dead"
    elif payload.get("source_liveness_required") is True:
        payload["product_visible"] = False
        payload["product_visibility_reason"] = "source_liveness_unverified"
    listing.raw_payload = payload


async def refresh_immmo_liveness(
    session: Session,
    *,
    limit: int | None = None,
) -> PropertyLivenessSummary:
    """Incrementally verify current IMMMO downstream URLs without touching detail metadata."""
    source = session.scalar(select(Source).where(Source.name == "immmo.at"))
    if source is None:
        return PropertyLivenessSummary()

    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=PROPERTY_LIVENESS_RECHECK_HOURS)
    checked_text = PropertyListing.raw_payload.op("->>")("source_liveness_checked_at")
    original_missing = func.coalesce(
        PropertyListing.raw_payload.op("->>")("original_url_missing"),
        "false",
    )
    reason = PropertyListing.raw_payload.op("->>")("product_visibility_reason")
    candidate_limit = max(1, limit or PROPERTY_LIVENESS_WORKER_LIMIT)

    listings = list(
        session.scalars(
            select(PropertyListing)
            .where(
                PropertyListing.source_id == source.id,
                PropertyListing.status == ListingStatus.ACTIVE,
                PropertyListing.raw_payload.is_not(None),
                original_missing != "true",
                reason.in_(("accepted", "source_dead", "source_liveness_unverified")),
                or_(
                    checked_text.is_(None),
                    cast(checked_text, DateTime(timezone=True)) <= cutoff,
                ),
            )
            .order_by(
                checked_text.asc().nullsfirst(),
                PropertyListing.first_seen_at.desc(),
                PropertyListing.id.desc(),
            )
            .limit(candidate_limit * 4)
        )
    )
    listings = [
        listing
        for listing in listings
        if property_budget_decision(_payload_price(listing.raw_payload or {})).accepted
    ][:candidate_limit]

    probes = await probe_property_urls([listing.url for listing in listings])
    counts = {"live": 0, "dead": 0, "unknown": 0}
    for listing in listings:
        probe = probes[listing.url]
        counts[probe.state] += 1
        _apply_persisted_probe(listing, probe)

    session.commit()
    return PropertyLivenessSummary(
        attempted=len(listings),
        live=counts["live"],
        dead=counts["dead"],
        unknown=counts["unknown"],
    )
