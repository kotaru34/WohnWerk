from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ListingStatus, PropertyListing, Source
from app.property_heating import extract_heating_evidence_from_html, merge_heating_into_payload

DEFAULT_SOURCE_NAMES = ("von-poll-de", "kleinanzeigen-de")
SOURCE_ALLOWED_HOSTS: dict[str, frozenset[str]] = {
    "von-poll-de": frozenset({"von-poll.com", "www.von-poll.com"}),
    "kleinanzeigen-de": frozenset({"kleinanzeigen.de", "www.kleinanzeigen.de"}),
}


@dataclass(frozen=True, slots=True)
class HeatingEnrichmentStats:
    considered: int = 0
    fetched: int = 0
    found: int = 0
    unknown: int = 0
    failed: int = 0


def _parse_checked_at(payload: dict | None) -> datetime | None:
    raw = (payload or {}).get("heating_checked_at")
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def heating_detail_due(
    payload: dict | None,
    *,
    now: datetime,
    refresh_after: timedelta,
) -> bool:
    checked = _parse_checked_at(payload)
    return checked is None or checked <= now - refresh_after


def apply_heating_detail_html(
    payload: dict | None,
    html: str,
    *,
    checked_at: datetime,
) -> dict:
    evidence = extract_heating_evidence_from_html(html)
    merged = merge_heating_into_payload(payload, evidence)
    merged["heating_checked_at"] = checked_at.astimezone(UTC).isoformat()
    merged["heating_enrichment_status"] = "found" if evidence.types else "unknown"
    merged.pop("heating_enrichment_error", None)
    return merged


def _allowed_detail_url(source_name: str, url: str) -> bool:
    allowed = SOURCE_ALLOWED_HOSTS.get(source_name)
    if not allowed:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and (parsed.hostname or "").casefold() in allowed


def _with_error(payload: dict | None, *, now: datetime, error: str) -> dict:
    result = dict(payload or {})
    result["heating_checked_at"] = now.astimezone(UTC).isoformat()
    result["heating_enrichment_status"] = "failed"
    result["heating_enrichment_error"] = error[:240]
    return result


async def enrich_active_property_heating(
    session: Session,
    *,
    source_names: Iterable[str] = DEFAULT_SOURCE_NAMES,
    limit: int = 50,
    delay_seconds: float = 3.0,
    timeout_seconds: float = 30.0,
    refresh_after: timedelta = timedelta(days=7),
) -> HeatingEnrichmentStats:
    requested_sources = tuple(dict.fromkeys(str(name) for name in source_names))
    unsupported = sorted(set(requested_sources) - set(SOURCE_ALLOWED_HOSTS))
    if unsupported:
        raise ValueError(f"Unsupported heating detail sources: {', '.join(unsupported)}")
    if limit <= 0:
        return HeatingEnrichmentStats()

    rows = list(
        session.execute(
            select(PropertyListing, Source.name)
            .join(Source, Source.id == PropertyListing.source_id)
            .where(
                PropertyListing.status == ListingStatus.ACTIVE,
                Source.name.in_(requested_sources),
            )
            .order_by(PropertyListing.id.desc())
        )
    )

    now = datetime.now(UTC)
    candidates: list[tuple[PropertyListing, str]] = []
    for listing, source_name in rows:
        if len(candidates) >= limit:
            break
        if not _allowed_detail_url(source_name, listing.url):
            continue
        if not heating_detail_due(
            listing.raw_payload,
            now=now,
            refresh_after=refresh_after,
        ):
            continue
        candidates.append((listing, source_name))

    considered = len(candidates)
    fetched = found = unknown = failed = 0
    headers = {
        "User-Agent": "WohnWerk/0.4 (+private self-hosted German property search)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
    }

    async with httpx.AsyncClient(
        headers=headers,
        timeout=timeout_seconds,
        follow_redirects=True,
    ) as client:
        for index, (listing, source_name) in enumerate(candidates):
            if index:
                await asyncio.sleep(max(2.0, delay_seconds) * random.uniform(0.85, 1.2))

            checked_at = datetime.now(UTC)
            try:
                response = await client.get(listing.url)
                final_host = (response.url.host or "").casefold()
                if final_host not in SOURCE_ALLOWED_HOSTS[source_name]:
                    raise RuntimeError(f"off-site redirect to {final_host or 'unknown host'}")
                if response.status_code in {401, 403, 429}:
                    raise RuntimeError(f"HTTP {response.status_code}")
                response.raise_for_status()
                fetched += 1
                listing.raw_payload = apply_heating_detail_html(
                    listing.raw_payload,
                    response.text,
                    checked_at=checked_at,
                )
                if listing.raw_payload.get("heating_types"):
                    found += 1
                else:
                    unknown += 1
            except (httpx.HTTPError, RuntimeError) as exc:
                listing.raw_payload = _with_error(
                    listing.raw_payload,
                    now=checked_at,
                    error=f"{type(exc).__name__}: {exc}",
                )
                failed += 1
            session.commit()

    return HeatingEnrichmentStats(
        considered=considered,
        fetched=fetched,
        found=found,
        unknown=unknown,
        failed=failed,
    )
