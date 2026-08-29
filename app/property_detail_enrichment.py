from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import ListingStatus, PropertyListing, Source
from app.property_acquisition import property_budget_decision
from app.property_detail_facts import (
    ImmoScoutPropertyFacts,
    extract_immoscout_property_facts,
    immoscout_facts_match_listing,
)

PROPERTY_DETAIL_FACTS_POLICY = "immoscout-structured-2026-08-29-v1"
PROPERTY_DETAIL_TIMEOUT_SECONDS = 10.0
PROPERTY_DETAIL_BODY_LIMIT_BYTES = 768 * 1024
PROPERTY_DETAIL_CONCURRENCY = 10
PROPERTY_DETAIL_WORKER_LIMIT = 60


@dataclass(frozen=True, slots=True)
class PropertyDetailEnrichmentSummary:
    considered: int = 0
    attempted: int = 0
    matched: int = 0
    missing: int = 0
    rejected: int = 0
    failed: int = 0
    prices_updated: int = 0
    plots_updated: int = 0
    living_updated: int = 0


@dataclass(frozen=True, slots=True)
class _FetchResult:
    body: str | None
    status_code: int | None
    error: str | None = None


def _payload_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


async def _fetch_one(
    client: httpx.AsyncClient,
    url: str,
    semaphore: asyncio.Semaphore,
) -> _FetchResult:
    try:
        async with semaphore, client.stream("GET", url) as response:
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                if total >= PROPERTY_DETAIL_BODY_LIMIT_BYTES:
                    break
                remaining = PROPERTY_DETAIL_BODY_LIMIT_BYTES - total
                chunks.append(chunk[:remaining])
                total += min(len(chunk), remaining)
            content = b"".join(chunks)
            encoding = response.encoding or "utf-8"
            try:
                body = content.decode(encoding, errors="replace")
            except LookupError:
                body = content.decode("utf-8", errors="replace")
            return _FetchResult(body=body, status_code=response.status_code)
    except httpx.HTTPError as exc:
        return _FetchResult(
            body=None,
            status_code=None,
            error=f"{type(exc).__name__}: {exc}"[:300],
        )


async def _fetch_many(urls: list[str]) -> dict[str, _FetchResult]:
    if not urls:
        return {}
    headers = {
        "User-Agent": "WohnWerk/0.3 (+private self-hosted Austrian property search; facts)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
    }
    semaphore = asyncio.Semaphore(PROPERTY_DETAIL_CONCURRENCY)
    async with httpx.AsyncClient(
        headers=headers,
        timeout=PROPERTY_DETAIL_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(
            *(_fetch_one(client, url, semaphore) for url in urls)
        )
    return dict(zip(urls, results, strict=True))


def _candidate_query(source_id: int, *, needle: str | None = None):
    payload_policy = PropertyListing.raw_payload.op("->>")("detail_facts_policy")
    stmt = (
        select(PropertyListing)
        .where(
            PropertyListing.source_id == source_id,
            PropertyListing.status == ListingStatus.ACTIVE,
            PropertyListing.url.ilike("%immobilienscout24.%"),
            func.coalesce(
                PropertyListing.raw_payload.op("->>")("original_url_missing"),
                "false",
            )
            != "true",
        )
        .options(selectinload(PropertyListing.property))
        .order_by(
            (payload_policy == PROPERTY_DETAIL_FACTS_POLICY).asc(),
            PropertyListing.first_seen_at.desc(),
            PropertyListing.id.desc(),
        )
    )
    if needle:
        stmt = stmt.where(PropertyListing.url.ilike(f"%{needle}%"))
    else:
        stmt = stmt.where(
            func.coalesce(payload_policy, "") != PROPERTY_DETAIL_FACTS_POLICY
        )
    return stmt


def _record_payload(
    listing: PropertyListing,
    *,
    state: str,
    facts: ImmoScoutPropertyFacts | None,
    status_code: int | None,
    error: str | None = None,
) -> dict:
    payload = dict(listing.raw_payload or {})
    payload["detail_facts_policy"] = PROPERTY_DETAIL_FACTS_POLICY
    payload["detail_facts_checked_at"] = datetime.now(UTC).isoformat()
    payload["detail_facts_state"] = state
    payload["detail_facts_status_code"] = status_code
    if error:
        payload["detail_facts_error"] = error
    else:
        payload.pop("detail_facts_error", None)
    if facts is not None:
        payload["detail_purchase_price_eur"] = (
            str(facts.purchase_price_eur) if facts.purchase_price_eur is not None else None
        )
        payload["detail_living_area_m2"] = (
            str(facts.living_area_m2) if facts.living_area_m2 is not None else None
        )
        payload["detail_plot_area_m2"] = (
            str(facts.plot_area_m2) if facts.plot_area_m2 is not None else None
        )
        payload["detail_postal_code"] = facts.postal_code
        payload["detail_object_number"] = facts.object_number
    listing.raw_payload = payload
    return payload


def _apply_facts(
    listing: PropertyListing,
    facts: ImmoScoutPropertyFacts,
    *,
    status_code: int | None,
) -> tuple[int, int, int]:
    property_row = listing.property
    payload = _record_payload(
        listing,
        state="matched",
        facts=facts,
        status_code=status_code,
    )
    prices_updated = 0
    plots_updated = 0
    living_updated = 0

    previous_source_price = _payload_decimal(payload.get("source_price_eur"))
    if facts.purchase_price_eur is not None:
        payload["source_price_eur"] = str(facts.purchase_price_eur)
        payload["price_semantics"] = "immoscout_structured"
        canonical_matches_source = (
            property_row.price_eur is None
            or previous_source_price is not None
            and property_row.price_eur == previous_source_price
        )
        if canonical_matches_source and property_row.price_eur != facts.purchase_price_eur:
            property_row.price_eur = facts.purchase_price_eur
            prices_updated = 1

        decision = property_budget_decision(facts.purchase_price_eur)
        if not decision.accepted:
            payload["product_visible"] = False
            payload["product_visibility_reason"] = decision.reason

    if property_row.plot_area_m2 is None and facts.plot_area_m2 is not None:
        property_row.plot_area_m2 = facts.plot_area_m2
        plots_updated = 1
    if property_row.living_area_m2 is None and facts.living_area_m2 is not None:
        property_row.living_area_m2 = facts.living_area_m2
        living_updated = 1

    listing.raw_payload = payload
    return prices_updated, plots_updated, living_updated


async def enrich_immoscout_property_facts(
    session: Session,
    *,
    limit: int = PROPERTY_DETAIL_WORKER_LIMIT,
    needle: str | None = None,
    apply: bool = True,
) -> PropertyDetailEnrichmentSummary:
    source = session.scalar(select(Source).where(Source.name == "immmo.at"))
    if source is None:
        return PropertyDetailEnrichmentSummary()

    listings = list(
        session.scalars(
            _candidate_query(source.id, needle=needle).limit(max(1, limit))
        )
    )
    fetches = await _fetch_many([listing.url for listing in listings])
    counts = {
        "matched": 0,
        "missing": 0,
        "rejected": 0,
        "failed": 0,
        "prices_updated": 0,
        "plots_updated": 0,
        "living_updated": 0,
    }

    for listing in listings:
        result = fetches[listing.url]
        if result.body is None or result.status_code is None or result.status_code >= 400:
            counts["failed"] += 1
            if apply:
                _record_payload(
                    listing,
                    state="failed",
                    facts=None,
                    status_code=result.status_code,
                    error=result.error or f"http_{result.status_code}",
                )
            continue

        facts = extract_immoscout_property_facts(listing.url, result.body)
        if facts is None:
            counts["missing"] += 1
            if apply:
                _record_payload(
                    listing,
                    state="missing",
                    facts=None,
                    status_code=result.status_code,
                )
            continue

        if not immoscout_facts_match_listing(
            facts,
            listing_url=listing.url,
            postal_code=listing.property.postal_code,
            title=listing.property.title,
        ):
            counts["rejected"] += 1
            if apply:
                _record_payload(
                    listing,
                    state="identity_rejected",
                    facts=facts,
                    status_code=result.status_code,
                )
            continue

        counts["matched"] += 1
        if apply:
            price, plot, living = _apply_facts(
                listing,
                facts,
                status_code=result.status_code,
            )
            counts["prices_updated"] += price
            counts["plots_updated"] += plot
            counts["living_updated"] += living

    if apply:
        session.commit()
    else:
        session.rollback()

    return PropertyDetailEnrichmentSummary(
        considered=len(listings),
        attempted=len(listings),
        matched=counts["matched"],
        missing=counts["missing"],
        rejected=counts["rejected"],
        failed=counts["failed"],
        prices_updated=counts["prices_updated"],
        plots_updated=counts["plots_updated"],
        living_updated=counts["living_updated"],
    )
