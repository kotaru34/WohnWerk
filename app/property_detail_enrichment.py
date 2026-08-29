from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import DateTime, and_, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import ListingStatus, PropertyListing, Source
from app.property_acquisition import property_budget_decision
from app.property_detail_facts import (
    PropertyDetailFacts,
    extract_property_detail_facts,
    property_facts_match_listing,
    supported_property_detail_url,
)

PROPERTY_DETAIL_FACTS_POLICY = "property-structured-2026-08-29-v4"
PROPERTY_DETAIL_TIMEOUT_SECONDS = 10.0
PROPERTY_DETAIL_BODY_LIMIT_BYTES = 768 * 1024
PROPERTY_DETAIL_CONCURRENCY = 10
PROPERTY_DETAIL_WORKER_LIMIT = 60
PROPERTY_DETAIL_RECHECK_HOURS = 24

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.6",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


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
    usable_updated: int = 0
    titles_updated: int = 0
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _FetchResult:
    body: str | None
    status_code: int | None
    final_url: str | None = None
    error: str | None = None


def _payload_decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _request_urls(listing: PropertyListing) -> tuple[str, ...]:
    values = [listing.url]
    final_url = (listing.raw_payload or {}).get("source_liveness_final_url")
    if supported_property_detail_url(final_url) and final_url not in values:
        values.append(str(final_url))
    return tuple(values)


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
            return _FetchResult(
                body=body,
                status_code=response.status_code,
                final_url=str(response.url),
            )
    except httpx.HTTPError as exc:
        return _FetchResult(
            body=None,
            status_code=None,
            final_url=None,
            error=f"{type(exc).__name__}: {exc}"[:300],
        )


async def _fetch_many(urls: list[str]) -> dict[str, _FetchResult]:
    if not urls:
        return {}
    unique_urls = list(dict.fromkeys(urls))
    semaphore = asyncio.Semaphore(PROPERTY_DETAIL_CONCURRENCY)
    async with httpx.AsyncClient(
        headers=_BROWSER_HEADERS,
        timeout=PROPERTY_DETAIL_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(
            *(_fetch_one(client, url, semaphore) for url in unique_urls)
        )
    return dict(zip(unique_urls, results, strict=True))


def _candidate_query(source_id: int, *, needle: str | None = None):
    payload_policy = PropertyListing.raw_payload.op("->>")("detail_facts_policy")
    state = PropertyListing.raw_payload.op("->>")("detail_facts_state")
    checked_text = PropertyListing.raw_payload.op("->>")("detail_facts_checked_at")
    checked_at = cast(checked_text, DateTime(timezone=True))
    retry_cutoff = datetime.now(UTC) - timedelta(hours=PROPERTY_DETAIL_RECHECK_HOURS)
    supported_url = or_(
        PropertyListing.url.ilike("%immobilienscout24.%"),
        PropertyListing.url.ilike("%findmyhome.at/%"),
    )
    stmt = (
        select(PropertyListing)
        .where(
            PropertyListing.source_id == source_id,
            PropertyListing.status == ListingStatus.ACTIVE,
            supported_url,
            func.coalesce(
                PropertyListing.raw_payload.op("->>")("original_url_missing"),
                "false",
            )
            != "true",
        )
        .options(selectinload(PropertyListing.property))
        .order_by(
            (payload_policy == PROPERTY_DETAIL_FACTS_POLICY).asc(),
            checked_at.asc().nullsfirst(),
            PropertyListing.first_seen_at.desc(),
            PropertyListing.id.desc(),
        )
    )
    if needle:
        stmt = stmt.where(
            or_(
                PropertyListing.url.ilike(f"%{needle}%"),
                PropertyListing.source_listing_id.ilike(f"%{needle}%"),
            )
        )
    else:
        stmt = stmt.where(
            or_(
                func.coalesce(payload_policy, "") != PROPERTY_DETAIL_FACTS_POLICY,
                and_(
                    state.in_(("failed", "missing")),
                    or_(checked_text.is_(None), checked_at <= retry_cutoff),
                ),
            )
        )
    return stmt


def _record_payload(
    listing: PropertyListing,
    *,
    state: str,
    facts: PropertyDetailFacts | None,
    status_code: int | None,
    final_url: str | None,
    error: str | None = None,
) -> dict:
    payload = dict(listing.raw_payload or {})
    payload["detail_facts_policy"] = PROPERTY_DETAIL_FACTS_POLICY
    payload["detail_facts_checked_at"] = datetime.now(UTC).isoformat()
    payload["detail_facts_state"] = state
    payload["detail_facts_status_code"] = status_code
    payload["detail_facts_final_url"] = final_url
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
        payload["detail_usable_area_m2"] = (
            str(facts.usable_area_m2) if facts.usable_area_m2 is not None else None
        )
        payload["detail_plot_area_m2"] = (
            str(facts.plot_area_m2) if facts.plot_area_m2 is not None else None
        )
        payload["detail_postal_code"] = facts.postal_code
        payload["detail_object_number"] = facts.object_number
        payload["detail_title"] = facts.title
        if facts.primary_image_url:
            payload["primary_image_url"] = facts.primary_image_url
            payload["primary_image_semantics"] = "provider_detail_metadata"
    listing.raw_payload = payload
    return payload


def _normalized_title(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.casefold().split())


def _detail_title_is_safe_upgrade(current: str | None, detail: str | None) -> bool:
    current_normalized = _normalized_title(current)
    detail_normalized = _normalized_title(detail)
    return bool(
        current_normalized
        and detail_normalized
        and current_normalized != detail_normalized
        and len(detail_normalized) > len(current_normalized)
        and current_normalized in detail_normalized
    )


def _restore_visibility_after_price_fix(payload: dict, decision) -> None:
    if not decision.accepted:
        payload["product_visible"] = False
        payload["product_visibility_reason"] = decision.reason
        return

    reason = str(payload.get("product_visibility_reason") or "")
    if not reason.startswith("price_"):
        return
    if payload.get("original_url_missing") is True:
        return
    if (
        payload.get("source_liveness_required") is True
        and payload.get("source_liveness_state") != "live"
    ):
        return
    payload["product_visible"] = True
    payload["product_visibility_reason"] = "accepted"


def _apply_facts(
    listing: PropertyListing,
    facts: PropertyDetailFacts,
    *,
    status_code: int | None,
    final_url: str | None,
) -> tuple[int, int, int, int, int]:
    property_row = listing.property
    previous_payload = dict(listing.raw_payload or {})
    previous_source_price = _payload_decimal(previous_payload.get("source_price_eur"))
    previous_usable = _payload_decimal(previous_payload.get("detail_usable_area_m2"))
    payload = _record_payload(
        listing,
        state="matched",
        facts=facts,
        status_code=status_code,
        final_url=final_url,
    )
    prices_updated = 0
    plots_updated = 0
    living_updated = 0
    usable_updated = 0
    titles_updated = 0

    if facts.purchase_price_eur is not None:
        payload["source_price_eur"] = str(facts.purchase_price_eur)
        payload["price_semantics"] = "provider_structured_detail"
        canonical_matches_source = (
            property_row.price_eur is None
            or previous_source_price is not None
            and property_row.price_eur == previous_source_price
        )
        if canonical_matches_source and property_row.price_eur != facts.purchase_price_eur:
            property_row.price_eur = facts.purchase_price_eur
            prices_updated = 1

        decision = property_budget_decision(facts.purchase_price_eur)
        _restore_visibility_after_price_fix(payload, decision)

    if property_row.plot_area_m2 is None and facts.plot_area_m2 is not None:
        property_row.plot_area_m2 = facts.plot_area_m2
        plots_updated = 1
    if property_row.living_area_m2 is None and facts.living_area_m2 is not None:
        property_row.living_area_m2 = facts.living_area_m2
        living_updated = 1
    if facts.usable_area_m2 is not None and previous_usable != facts.usable_area_m2:
        usable_updated = 1
    if _detail_title_is_safe_upgrade(property_row.title, facts.title):
        property_row.title = str(facts.title)
        titles_updated = 1

    listing.raw_payload = payload
    return prices_updated, plots_updated, living_updated, usable_updated, titles_updated


def _result_error(result: _FetchResult) -> str:
    if result.error:
        return result.error
    if result.status_code is None:
        return "request_failed"
    return f"http_{result.status_code}"


async def enrich_immoscout_property_facts(
    session: Session,
    *,
    limit: int = PROPERTY_DETAIL_WORKER_LIMIT,
    needle: str | None = None,
    apply: bool = True,
) -> PropertyDetailEnrichmentSummary:
    """Enrich supported IMMMO downstream details.

    The public function keeps its historical name for script compatibility. It now
    dispatches only to explicitly supported providers rather than being ImmoScout-only.
    """
    source = session.scalar(select(Source).where(Source.name == "immmo.at"))
    if source is None:
        return PropertyDetailEnrichmentSummary()

    listings = list(
        session.scalars(
            _candidate_query(source.id, needle=needle).limit(max(1, limit))
        )
    )
    request_urls_by_listing = {
        listing.id: _request_urls(listing)
        for listing in listings
    }
    fetches = await _fetch_many(
        [
            url
            for listing in listings
            for url in request_urls_by_listing[listing.id]
        ]
    )
    counts = {
        "matched": 0,
        "missing": 0,
        "rejected": 0,
        "failed": 0,
        "prices_updated": 0,
        "plots_updated": 0,
        "living_updated": 0,
        "usable_updated": 0,
        "titles_updated": 0,
    }
    details: list[str] = []

    for listing in listings:
        attempts = [
            (url, fetches[url])
            for url in request_urls_by_listing[listing.id]
        ]
        successful = [
            (url, result)
            for url, result in attempts
            if result.body is not None
            and result.status_code is not None
            and result.status_code < 400
        ]
        if not successful:
            counts["failed"] += 1
            last_url, last_result = attempts[-1]
            diagnostic = (
                f"listing={listing.id} state=failed status={last_result.status_code} "
                f"request_url={last_url} final_url={last_result.final_url} "
                f"error={_result_error(last_result)}"
            )
            details.append(diagnostic)
            if apply:
                _record_payload(
                    listing,
                    state="failed",
                    facts=None,
                    status_code=last_result.status_code,
                    final_url=last_result.final_url,
                    error=_result_error(last_result),
                )
            continue

        facts = None
        selected_url = None
        selected_result = None
        for request_url, result in successful:
            candidate = extract_property_detail_facts(request_url, result.body or "")
            if candidate is not None:
                facts = candidate
                selected_url = request_url
                selected_result = result
                break

        if facts is None or selected_result is None or selected_url is None:
            counts["missing"] += 1
            request_url, result = successful[-1]
            details.append(
                f"listing={listing.id} state=missing status={result.status_code} "
                f"request_url={request_url} final_url={result.final_url}"
            )
            if apply:
                _record_payload(
                    listing,
                    state="missing",
                    facts=None,
                    status_code=result.status_code,
                    final_url=result.final_url,
                )
            continue

        if not property_facts_match_listing(
            facts,
            listing_url=listing.url,
            postal_code=listing.property.postal_code,
            title=listing.property.title,
        ):
            counts["rejected"] += 1
            details.append(
                f"listing={listing.id} state=rejected status={selected_result.status_code} "
                f"price={facts.purchase_price_eur} living={facts.living_area_m2} "
                f"plot={facts.plot_area_m2} zip={facts.postal_code} "
                f"object={facts.object_number} final_url={selected_result.final_url}"
            )
            if apply:
                _record_payload(
                    listing,
                    state="identity_rejected",
                    facts=facts,
                    status_code=selected_result.status_code,
                    final_url=selected_result.final_url,
                )
            continue

        counts["matched"] += 1
        details.append(
            f"listing={listing.id} state=matched status={selected_result.status_code} "
            f"price={facts.purchase_price_eur} living={facts.living_area_m2} "
            f"usable={facts.usable_area_m2} plot={facts.plot_area_m2} "
            f"zip={facts.postal_code} object={facts.object_number} "
            f"image={'yes' if facts.primary_image_url else 'no'} "
            f"final_url={selected_result.final_url}"
        )
        if apply:
            price, plot, living, usable, title = _apply_facts(
                listing,
                facts,
                status_code=selected_result.status_code,
                final_url=selected_result.final_url,
            )
            counts["prices_updated"] += price
            counts["plots_updated"] += plot
            counts["living_updated"] += living
            counts["usable_updated"] += usable
            counts["titles_updated"] += title

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
        usable_updated=counts["usable_updated"],
        titles_updated=counts["titles_updated"],
        details=tuple(details),
    )
