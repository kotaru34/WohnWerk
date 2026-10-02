from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError
from sqlalchemy import DateTime, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.internet_source_evidence import (
    ParsedInternetDetail,
    parse_immowelt_de_internet_evidence,
    replace_listing_internet_source_evidence,
)
from app.models import ListingStatus, PropertyListing, Source
from app.property_heating_enrichment import apply_heating_detail_html
from app.sources.base import SourceChallenge
from app.sources.property.immowelt_de import detect_immowelt_challenge

INTERNET_DETAIL_POLICY = "de-internet-source-detail-2026-09-27-v1"
INTERNET_DETAIL_RECHECK_HOURS = 168
INTERNET_DETAIL_WORKER_LIMIT = 40
INTERNET_DETAIL_TIMEOUT_SECONDS = 35.0
INTERNET_DETAIL_DELAY_SECONDS = 1.25
_IMMOWELT_HOSTS = {"immowelt.de", "www.immowelt.de"}
_EXPOSE_TOKEN_RE = re.compile(r"^/expose/(?P<token>[a-z0-9-]+?)/?$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class InternetDetailEnrichmentSummary:
    considered: int = 0
    attempted: int = 0
    matched: int = 0
    missing: int = 0
    challenged: int = 0
    failed: int = 0
    evidence_rows: int = 0
    halted: bool = False
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _FetchResult:
    body: str
    final_url: str
    status_code: int


class ImmoweltInternetDetailFetcher:
    """Bounded ordinary-browser fetcher. It never invokes an external challenge handler."""

    def __init__(
        self,
        *,
        timeout_seconds: float = INTERNET_DETAIL_TIMEOUT_SECONDS,
        delay_seconds: float = INTERNET_DETAIL_DELAY_SECONDS,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.delay_seconds = max(1.0, delay_seconds)
        self._requests_made = 0
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def _ensure_page(self) -> Page:
        if self._page is not None:
            return self._page
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(locale="de-DE")

        async def block_heavy_assets(route) -> None:
            if route.request.resource_type in {"font", "image", "media"}:
                await route.abort()
            else:
                await route.continue_()

        await self._context.route("**/*", block_heavy_assets)
        self._page = await self._context.new_page()
        return self._page

    async def aclose(self) -> None:
        try:
            if self._page is not None:
                await self._page.close()
        finally:
            try:
                if self._context is not None:
                    await self._context.close()
            finally:
                try:
                    if self._browser is not None:
                        await self._browser.close()
                finally:
                    if self._playwright is not None:
                        await self._playwright.stop()
                    self._page = None
                    self._context = None
                    self._browser = None
                    self._playwright = None

    async def fetch(self, url: str) -> _FetchResult:
        if self._requests_made:
            await asyncio.sleep(self.delay_seconds)
        self._requests_made += 1

        page = await self._ensure_page()
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=int(self.timeout_seconds * 1000),
        )
        if response is None:
            raise RuntimeError("Immowelt detail navigation returned no response")
        await page.wait_for_timeout(350)

        status = response.status
        body = await page.content()
        challenge = detect_immowelt_challenge(
            status=status,
            requested_url=url,
            final_url=page.url,
            html=body,
            frame_urls=[frame.url for frame in page.frames],
        )
        if challenge is not None:
            raise SourceChallenge(
                f"Immowelt detail access challenge detected ({challenge['kind']})",
                challenge=challenge,
            )
        if status == 429:
            raise RuntimeError("Immowelt detail HTTP 429")
        if status >= 400:
            raise RuntimeError(f"Immowelt detail HTTP {status}")

        final = urlparse(page.url)
        if (final.hostname or "").casefold() not in _IMMOWELT_HOSTS:
            raise RuntimeError(f"Immowelt detail redirected off-site: {page.url!r}")
        return _FetchResult(body=body, final_url=page.url, status_code=status)


def _expose_token(url: str) -> str | None:
    parsed = urlparse(url)
    if (parsed.hostname or "").casefold() not in _IMMOWELT_HOSTS:
        return None
    match = _EXPOSE_TOKEN_RE.match(parsed.path)
    return match.group("token").casefold() if match is not None else None


def _candidate_query(source_id: int):
    payload_policy = PropertyListing.raw_payload.op("->>")("internet_evidence_policy")
    checked_text = PropertyListing.raw_payload.op("->>")("internet_evidence_checked_at")
    checked_at = cast(checked_text, DateTime(timezone=True))
    cutoff = datetime.now(UTC) - timedelta(hours=INTERNET_DETAIL_RECHECK_HOURS)
    return (
        select(PropertyListing)
        .where(
            PropertyListing.source_id == source_id,
            PropertyListing.status == ListingStatus.ACTIVE,
            or_(
                func.coalesce(payload_policy, "") != INTERNET_DETAIL_POLICY,
                checked_text.is_(None),
                checked_at <= cutoff,
            ),
        )
        .options(selectinload(PropertyListing.property))
        .order_by(
            checked_at.asc().nullsfirst(),
            PropertyListing.last_seen_at.desc(),
            PropertyListing.id.desc(),
        )
    )


def _record_state(
    listing: PropertyListing,
    *,
    state: str,
    final_url: str | None = None,
    status_code: int | None = None,
    evidence_count: int | None = None,
    error: str | None = None,
) -> None:
    payload = dict(listing.raw_payload or {})
    payload["internet_evidence_policy"] = INTERNET_DETAIL_POLICY
    payload["internet_evidence_checked_at"] = datetime.now(UTC).isoformat()
    payload["internet_evidence_state"] = state
    if final_url is not None:
        payload["internet_evidence_final_url"] = final_url
    if status_code is not None:
        payload["internet_evidence_status_code"] = status_code
    if evidence_count is not None:
        payload["internet_evidence_count"] = evidence_count
    if error:
        payload["internet_evidence_error"] = error[:300]
    else:
        payload.pop("internet_evidence_error", None)
    listing.raw_payload = payload


def _identity_matches(listing: PropertyListing, final_url: str) -> bool:
    expected = _expose_token(listing.url)
    final = _expose_token(final_url)
    return bool(expected and final and expected == final)


async def enrich_de_internet_source_evidence(
    session: Session,
    *,
    limit: int = INTERNET_DETAIL_WORKER_LIMIT,
    apply: bool = True,
) -> InternetDetailEnrichmentSummary:
    source = session.scalar(select(Source).where(Source.name == "immowelt-de"))
    if source is None:
        return InternetDetailEnrichmentSummary()

    listings = list(
        session.scalars(_candidate_query(source.id).limit(max(1, limit)))
    )
    details: list[str] = []
    counts = {
        "matched": 0,
        "missing": 0,
        "challenged": 0,
        "failed": 0,
        "evidence_rows": 0,
    }
    halted = False

    fetcher = ImmoweltInternetDetailFetcher()
    try:
        for listing in listings:
            try:
                result = await fetcher.fetch(listing.url)
            except SourceChallenge as exc:
                counts["challenged"] += 1
                halted = True
                details.append(
                    f"listing={listing.id} state=challenged "
                    f"kind={exc.challenge.get('kind', 'unknown')}"
                )
                if apply:
                    _record_state(
                        listing,
                        state="challenged",
                        error=f"challenge:{exc.challenge.get('kind', 'unknown')}",
                    )
                    session.commit()
                break
            except (PlaywrightError, RuntimeError) as exc:
                counts["failed"] += 1
                details.append(
                    f"listing={listing.id} state=failed error={type(exc).__name__}"
                )
                if apply:
                    _record_state(
                        listing,
                        state="failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    session.commit()
                continue

            if not _identity_matches(listing, result.final_url):
                counts["failed"] += 1
                details.append(f"listing={listing.id} state=identity_mismatch")
                if apply:
                    _record_state(
                        listing,
                        state="failed",
                        final_url=result.final_url,
                        status_code=result.status_code,
                        error="detail_identity_mismatch",
                    )
                    session.commit()
                continue

            parsed: ParsedInternetDetail = parse_immowelt_de_internet_evidence(
                result.final_url,
                result.body,
            )
            evidence_count = len(parsed.claims) + (
                1 if parsed.source_address and not parsed.claims else 0
            )
            if parsed.has_evidence:
                counts["matched"] += 1
                details.append(
                    f"listing={listing.id} state=matched claims={evidence_count} "
                    f"address={bool(parsed.source_address)}"
                )
            else:
                counts["missing"] += 1
                details.append(f"listing={listing.id} state=missing")

            if apply:
                stored = replace_listing_internet_source_evidence(
                    session,
                    listing=listing,
                    source_name=source.name,
                    parsed=parsed,
                )
                counts["evidence_rows"] += stored
                _record_state(
                    listing,
                    state="matched" if parsed.has_evidence else "missing",
                    final_url=result.final_url,
                    status_code=result.status_code,
                    evidence_count=stored,
                )
                # Reuse the already fetched Immowelt detail HTML for heating facts.
                # This adds no portal request and retains only normalized heating
                # types plus bounded source-backed evidence, never the full body.
                listing.raw_payload = apply_heating_detail_html(
                    listing.raw_payload,
                    result.body,
                    checked_at=datetime.now(UTC),
                )
                session.commit()
            else:
                counts["evidence_rows"] += evidence_count
    finally:
        await fetcher.aclose()

    return InternetDetailEnrichmentSummary(
        considered=len(listings),
        attempted=(
            counts["matched"]
            + counts["missing"]
            + counts["challenged"]
            + counts["failed"]
        ),
        matched=counts["matched"],
        missing=counts["missing"],
        challenged=counts["challenged"],
        failed=counts["failed"],
        evidence_rows=counts["evidence_rows"],
        halted=halted,
        details=tuple(details),
    )
