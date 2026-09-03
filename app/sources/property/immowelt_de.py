from __future__ import annotations

import asyncio
import math
import random
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.sources.base import (
    PropertySource,
    RawProperty,
    SourceBatch,
    SourceChallenge,
    SourceFetchError,
    SourceShardSpec,
)
from app.sources.property.germany import (
    GERMAN_REGIONS,
    PRICE_BANDS_BY_KEY,
    PROPERTY_PRICE_BANDS,
    REGIONS_BY_KEY,
)
from app.sources.property.immmo import _clean_text, _decimal, _DOMParser, _Node

BASE_URL = "https://www.immowelt.de"
SEARCH_URL = f"{BASE_URL}/classified-search"
PAGE_SIZE = 40
PROVIDER_PAGE_CAP = 250
CARD_TEST_ID = "serp-core-classified-card-testid"
COVERING_LINK_TEST_ID = "card-mfe-covering-link-testid"
ADDRESS_TEST_ID = "cardmfe-description-box-address"
_EXPOSE_RE = re.compile(
    r"^/expose/(?P<listing_id>(?:[0-9a-f-]{20,}|[a-z0-9]{12}))/?$",
    re.IGNORECASE,
)
_PROJECT_EXPOSE_RE = re.compile(
    r"^/projekte/expose/(?P<project_id>[a-z0-9-]{4,})/?$",
    re.IGNORECASE,
)
_POSTAL_RE = re.compile(r"\b(?P<postal_code>\d{5})\b")
_PLOT_RE = re.compile(r"(?P<area>[\d.]+(?:,\d+)?)\s*m(?:²|2)\s*Grundstück", re.IGNORECASE)
_AREA_RE = re.compile(r"(?P<area>[\d.]+(?:,\d+)?)\s*m(?:²|2)\b", re.IGNORECASE)
_TOTAL_RE = re.compile(
    r"(?P<count>[\d.]+)\s+(?:Günstige\s+)?(?:Haus|Häuser)\b",
    re.IGNORECASE,
)
_PRICE_ON_REQUEST_RE = re.compile(r"^Preis\s+auf\s+Anfrage$", re.IGNORECASE)
_SEARCH_STATE_KEYS = (
    "distributionTypes",
    "estateTypes",
    "locations",
    "priceMin",
    "priceMax",
    "order",
)
_CHALLENGE_HOST_SUFFIXES = (
    "captcha-delivery.com",
    "captcha-delivery.net",
)
_CHALLENGE_STRONG_MARKERS = (
    "ich bin kein roboter",
    "verify you are human",
    "are you a human",
    "access denied",
    "zugriff verweigert",
    "captcha-delivery.com",
    "captcha-delivery.net",
    "dd_captcha",
    "geo.captcha-delivery",
)


@dataclass(frozen=True, slots=True)
class ImmoweltPage:
    items: list[RawProperty]
    source_reported_count: int
    max_page: int
    cards_seen: int
    cards_parsed: int
    cards_total: int
    project_cards_skipped: int
    blank_cards_skipped: int


def detect_immowelt_challenge(
    *,
    status: int | None,
    requested_url: str,
    final_url: str,
    html: str,
    frame_urls: list[str] | tuple[str, ...] = (),
) -> dict[str, Any] | None:
    """Recognize explicit source gates without treating ordinary portal JS as a challenge."""
    if status == 403:
        return {
            "kind": "http_403",
            "http_status": 403,
            "requested_url": requested_url,
            "final_url": final_url,
        }

    suspicious_url: str | None = None
    for candidate in (final_url, *frame_urls):
        host = (urlparse(candidate).hostname or "").casefold()
        if any(host == suffix or host.endswith(f".{suffix}") for suffix in _CHALLENGE_HOST_SUFFIXES):
            suspicious_url = candidate
            break
    if suspicious_url is not None:
        return {
            "kind": "challenge_frame_or_redirect",
            "http_status": status,
            "requested_url": requested_url,
            "final_url": final_url,
            "challenge_url": suspicious_url,
        }

    lowered = html.casefold()
    markers = [marker for marker in _CHALLENGE_STRONG_MARKERS if marker in lowered]
    if markers:
        return {
            "kind": "challenge_content",
            "http_status": status,
            "requested_url": requested_url,
            "final_url": final_url,
            "markers": markers[:5],
        }

    # Avoid false positives from a normal page merely loading a generic CAPTCHA library.
    # Generic "captcha" only counts when the document itself also looks like a challenge UI.
    if "captcha" in lowered and (
        "<iframe" in lowered
        or "challenge" in lowered
        or "robot" in lowered
        or "human" in lowered
    ):
        return {
            "kind": "challenge_content",
            "http_status": status,
            "requested_url": requested_url,
            "final_url": final_url,
            "markers": ["captcha+challenge-ui"],
        }
    return None


def _node_by_test_id(card: _Node, test_id: str) -> _Node | None:
    return next(
        (node for node in card.walk() if node.attrs.get("data-testid") == test_id),
        None,
    )


def _canonical_expose_url(raw_url: str) -> tuple[str, str] | None:
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or host not in {"immowelt.de", "www.immowelt.de"}:
        return None
    match = _EXPOSE_RE.match(parsed.path)
    if match is None:
        return None
    listing_id = match.group("listing_id").casefold()
    return f"{BASE_URL}/expose/{listing_id}", listing_id


def _is_project_expose_url(raw_url: str) -> bool:
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").casefold()
    return bool(
        parsed.scheme in {"http", "https"}
        and host in {"immowelt.de", "www.immowelt.de"}
        and _PROJECT_EXPOSE_RE.match(parsed.path)
    )


def _title_facts(raw_title: str) -> tuple[str, str | None, str | None]:
    cleaned = _clean_text(raw_title)
    parts = [_clean_text(part) for part in cleaned.split(" - ") if _clean_text(part)]
    if len(parts) < 3:
        return cleaned[:500], None, None

    price_index: int | None = None
    for index, part in enumerate(parts):
        if "€" in part or _PRICE_ON_REQUEST_RE.fullmatch(part):
            price_index = index
            break

    if price_index is None or price_index < 2:
        return cleaned[:500], None, None

    city = parts[price_index - 1] or None
    title = " - ".join(parts[: price_index - 1]) or parts[0]
    return title[:500], city, parts[price_index]


def _areas(raw_title: str) -> tuple[Decimal | None, Decimal | None]:
    plot_match = _PLOT_RE.search(raw_title)
    plot = _decimal(plot_match.group("area")) if plot_match is not None else None
    living = None
    for match in _AREA_RE.finditer(raw_title):
        suffix = raw_title[match.end() : match.end() + 20]
        if re.match(r"\s*Grundstück", suffix, re.IGNORECASE):
            continue
        living = _decimal(match.group("area"))
        break
    return living, plot


def _postal_from_card(card: _Node) -> str | None:
    address = _node_by_test_id(card, ADDRESS_TEST_ID)
    if address is not None:
        match = _POSTAL_RE.search(_clean_text(address.text()))
        if match is not None:
            return match.group("postal_code")

    for node in card.walk():
        if node.tag != "img":
            continue
        match = _POSTAL_RE.search(_clean_text(node.attrs.get("alt", "")))
        if match is not None:
            return match.group("postal_code")
    return None


def _page_count(root: _Node) -> tuple[int, int]:
    match = next(
        (
            heading_match
            for node in root.walk()
            if node.tag == "h1"
            if (heading_match := _TOTAL_RE.search(node.text())) is not None
        ),
        None,
    )
    if match is None:
        raise ValueError("Immowelt result count is missing")
    count = int(match.group("count").replace(".", ""))
    pages = [max(1, math.ceil(count / PAGE_SIZE))]
    for node in root.walk():
        label = node.attrs.get("aria-label", "")
        page_match = re.fullmatch(r"zu seite (?P<page>\d+)", label, re.IGNORECASE)
        if page_match is not None:
            pages.append(int(page_match.group("page")))
    return count, max(pages)


def parse_immowelt_search_page(
    html: str,
    *,
    page_url: str,
    region_key: str,
    price_band_key: str,
) -> ImmoweltPage:
    parser = _DOMParser()
    parser.feed(html)
    source_reported_count, max_page = _page_count(parser.root)
    cards = [node for node in parser.root.walk() if node.attrs.get("data-testid") == CARD_TEST_ID]

    items: list[RawProperty] = []
    identity_cards_seen = 0
    project_cards_skipped = 0
    blank_cards_skipped = 0
    for card in cards:
        anchor = _node_by_test_id(card, COVERING_LINK_TEST_ID)
        if anchor is None:
            if not _clean_text(card.text()):
                blank_cards_skipped += 1
                continue
            identity_cards_seen += 1
            continue

        raw_href = anchor.attrs.get("href", "")
        if _is_project_expose_url(raw_href):
            project_cards_skipped += 1
            continue

        identity_cards_seen += 1
        detail = _canonical_expose_url(raw_href)
        if detail is None:
            continue
        url, listing_id = detail
        raw_title = anchor.attrs.get("title", "")
        title, city, price_text = _title_facts(raw_title)
        living_area, plot_area = _areas(raw_title)
        postal_code = _postal_from_card(card)

        items.append(
            RawProperty(
                source_listing_id=listing_id,
                url=url,
                title=title or f"Haus zum Kauf {listing_id}",
                description=None,
                price_eur=_decimal(price_text),
                living_area_m2=living_area,
                plot_area_m2=plot_area,
                postal_code=postal_code,
                city=city,
                raw_payload={
                    "format": "immowelt-public-search-v2",
                    "country_code": "DE",
                    "discovery_url": page_url,
                    "region_key": region_key,
                    "price_band_key": price_band_key,
                    "source_postal_code": postal_code,
                    "identity_stable": True,
                },
            )
        )

    return ImmoweltPage(
        items=items,
        source_reported_count=source_reported_count,
        max_page=max_page,
        cards_seen=identity_cards_seen,
        cards_parsed=len(items),
        cards_total=len(cards),
        project_cards_skipped=project_cards_skipped,
        blank_cards_skipped=blank_cards_skipped,
    )


def _validate_page(page: ImmoweltPage, *, page_number: int, expected_minimum: int) -> None:
    if page.source_reported_count and page.cards_total == 0:
        raise RuntimeError(f"Immowelt returned no cards on non-empty page {page_number}")
    if page.cards_seen != page.cards_parsed:
        raise RuntimeError(
            f"Immowelt card parsing incomplete on page {page_number}: "
            f"parsed {page.cards_parsed}/{page.cards_seen} identity-bearing cards"
        )
    if expected_minimum and page.cards_total < expected_minimum:
        raise RuntimeError(
            f"Immowelt page {page_number} unexpectedly short: "
            f"saw {page.cards_total}, expected at least {expected_minimum}"
        )


def _validate_search_state(requested_url: str, final_url: str) -> None:
    requested = urlparse(requested_url)
    final = urlparse(final_url)

    if final.path != "/classified-search":
        raise RuntimeError(f"Immowelt search state redirected unexpectedly: {final_url!r}")

    expected = parse_qs(requested.query)
    actual = parse_qs(final.query)

    for key in _SEARCH_STATE_KEYS:
        if actual.get(key) != expected.get(key):
            raise RuntimeError(
                f"Immowelt search state lost {key}: "
                f"expected {expected.get(key)!r}, got {actual.get(key)!r}"
            )

    expected_page = (expected.get("page") or ["1"])[0]
    actual_page = (actual.get("page") or ["1"])[0]
    if actual_page != expected_page:
        raise RuntimeError(
            f"Immowelt search state lost page: expected {expected_page!r}, got {actual_page!r}"
        )


def _integer_cursor(cursor: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(cursor.get(key, default))
    except (TypeError, ValueError):
        return default


class ImmoweltGermanyPropertySource(PropertySource):
    """Public-browser Immowelt adapter with explicit resumable challenge detection."""

    name = "immowelt-de"

    def __init__(
        self,
        *,
        request_delay_seconds: float = 1.5,
        incremental_pages: int = 2,
        hard_max_pages: int = PROVIDER_PAGE_CAP,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.request_delay_seconds = max(1.0, request_delay_seconds)
        self.incremental_pages = max(1, incremental_pages)
        self.hard_max_pages = min(PROVIDER_PAGE_CAP, max(10, hard_max_pages))
        self.timeout_seconds = timeout_seconds
        self._requests_made = 0
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=f"{region.key}:{band.key}",
                params={"region_key": region.key, "price_band_key": band.key},
                result_cap=self.hard_max_pages * PAGE_SIZE,
            )
            for region in GERMAN_REGIONS
            for band in PROPERTY_PRICE_BANDS
        ]

    async def _ensure_page(self) -> Page:
        if self._page is not None:
            return self._page
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(locale="de-DE")

        async def block_heavy_assets(route: Any) -> None:
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

    async def _sleep(self) -> None:
        await asyncio.sleep(self.request_delay_seconds * random.uniform(0.8, 1.25))

    @staticmethod
    def _page_url(region_key: str, price_band_key: str, page: int) -> str:
        region = REGIONS_BY_KEY.get(region_key)
        band = PRICE_BANDS_BY_KEY.get(price_band_key)
        if region is None or band is None:
            raise ValueError(
                f"Invalid Immowelt shard: region={region_key!r} band={price_band_key!r}"
            )
        query = urlencode(
            {
                "distributionTypes": "Buy,Buy_Auction,Compulsory_Auction",
                "estateTypes": "House",
                "locations": region.immowelt_location_id,
                "priceMax": band.maximum_eur,
                "priceMin": band.minimum_eur,
                "order": "DateDesc",
                "page": page,
            }
        )
        return f"{SEARCH_URL}?{query}"

    async def _challenge_probe(
        self,
        *,
        page: Page,
        requested_url: str,
        status: int | None,
    ) -> dict[str, Any] | None:
        try:
            html = await page.content()
        except PlaywrightError:
            html = ""
        frame_urls = [frame.url for frame in page.frames]
        return detect_immowelt_challenge(
            status=status,
            requested_url=requested_url,
            final_url=page.url,
            html=html,
            frame_urls=frame_urls,
        )

    async def _load_html(self, url: str) -> tuple[str, str]:
        if self._requests_made:
            await self._sleep()
        self._requests_made += 1
        page = await self._ensure_page()
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=int(self.timeout_seconds * 1000),
        )
        if response is None:
            raise RuntimeError("Immowelt navigation returned no response")

        status = response.status
        challenge = await self._challenge_probe(page=page, requested_url=url, status=status)
        if challenge is not None:
            raise SourceChallenge(
                f"Immowelt access challenge detected ({challenge['kind']})",
                challenge=challenge,
            )
        if status == 429:
            raise SourceFetchError("Immowelt HTTP 429 rate limit", halt_source=True)
        if status >= 400:
            raise RuntimeError(f"Immowelt HTTP {status}")

        host = (urlparse(page.url).hostname or "").casefold()
        if host not in {"immowelt.de", "www.immowelt.de"}:
            challenge = await self._challenge_probe(page=page, requested_url=url, status=status)
            if challenge is not None:
                raise SourceChallenge(
                    f"Immowelt access challenge detected ({challenge['kind']})",
                    challenge=challenge,
                )
            raise RuntimeError(f"Immowelt redirected off-site: {page.url!r}")

        try:
            await page.wait_for_selector("h1", timeout=int(self.timeout_seconds * 1000))
        except PlaywrightTimeoutError as exc:
            challenge = await self._challenge_probe(page=page, requested_url=url, status=status)
            if challenge is not None:
                raise SourceChallenge(
                    f"Immowelt access challenge detected ({challenge['kind']})",
                    challenge=challenge,
                ) from exc
            raise

        try:
            await page.wait_for_selector(
                f'[data-testid="{CARD_TEST_ID}"]',
                timeout=min(8000, int(self.timeout_seconds * 1000)),
            )
        except PlaywrightTimeoutError:
            pass
        await page.wait_for_timeout(500)

        challenge = await self._challenge_probe(page=page, requested_url=url, status=status)
        if challenge is not None:
            raise SourceChallenge(
                f"Immowelt access challenge detected ({challenge['kind']})",
                challenge=challenge,
            )

        _validate_search_state(url, page.url)
        return await page.content(), page.url

    def _progress_cursor(
        self,
        *,
        region_key: str,
        price_band_key: str,
        resume_page: int,
        completed_pages: int,
        target_pages: int,
        cards_seen: int,
        cards_parsed: int,
        cards_total: int,
        project_cards_skipped: int,
        blank_cards_skipped: int,
        max_page: int,
        source_reported_count: int | None,
        latest_reported_count: int | None,
        max_reported_count: int,
        seen_ids: set[str],
        identity_history_complete: bool,
    ) -> dict[str, Any]:
        region = REGIONS_BY_KEY[region_key]
        return {
            "_resume_same_run": True,
            "resume_page": resume_page,
            "discovery_completed_pages": completed_pages,
            "discovery_target_pages": target_pages,
            "discovery_cards_seen": cards_seen,
            "discovery_cards_parsed": cards_parsed,
            "discovery_cards_total": cards_total,
            "discovery_project_cards_skipped": project_cards_skipped,
            "discovery_blank_cards_skipped": blank_cards_skipped,
            "discovery_max_page": max_page,
            "discovery_initial_reported_count": source_reported_count,
            "discovery_latest_reported_count": latest_reported_count,
            "discovery_max_reported_count": max_reported_count,
            "discovery_seen_ids": sorted(seen_ids),
            "discovery_identity_history_complete": identity_history_complete,
            "region_key": region_key,
            "bundesland": region.label,
            "price_band_key": price_band_key,
            "country_code": "DE",
        }

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        region_key = str(shard.params.get("region_key") or "")
        price_band_key = str(shard.params.get("price_band_key") or "")
        region = REGIONS_BY_KEY.get(region_key)
        if region is None:
            raise ValueError(f"Unknown Immowelt region {region_key!r}")
        self._page_url(region_key, price_band_key, 1)

        resume = dict(cursor or {}) if (cursor or {}).get("_resume_same_run") is True else {}
        page_number = max(1, _integer_cursor(resume, "resume_page", 1))
        completed_pages = max(0, _integer_cursor(resume, "discovery_completed_pages", 0))
        target_pages = max(1, _integer_cursor(resume, "discovery_target_pages", 1))
        cards_seen = max(0, _integer_cursor(resume, "discovery_cards_seen", 0))
        cards_parsed = max(0, _integer_cursor(resume, "discovery_cards_parsed", 0))
        cards_total = max(0, _integer_cursor(resume, "discovery_cards_total", 0))
        project_cards_skipped = max(
            0, _integer_cursor(resume, "discovery_project_cards_skipped", 0)
        )
        blank_cards_skipped = max(
            0, _integer_cursor(resume, "discovery_blank_cards_skipped", 0)
        )
        max_page = max(1, _integer_cursor(resume, "discovery_max_page", 1))
        max_reported_count = max(0, _integer_cursor(resume, "discovery_max_reported_count", 0))
        source_reported_count = resume.get("discovery_initial_reported_count")
        latest_reported_count = resume.get("discovery_latest_reported_count")
        if source_reported_count is not None:
            source_reported_count = int(source_reported_count)
        if latest_reported_count is not None:
            latest_reported_count = int(latest_reported_count)

        persisted_seen_ids = resume.get("discovery_seen_ids")
        identity_history_complete = not resume or isinstance(persisted_seen_ids, list)
        seen_ids = (
            {str(listing_id) for listing_id in persisted_seen_ids if listing_id}
            if isinstance(persisted_seen_ids, list)
            else set()
        )

        items_by_id: dict[str, RawProperty] = {}
        pages_fetched = 0
        result_cap_hit = max_page >= self.hard_max_pages

        try:
            while True:
                requested_url = self._page_url(region_key, price_band_key, page_number)
                page_html, page_url = await self._load_html(requested_url)
                page = parse_immowelt_search_page(
                    page_html,
                    page_url=page_url,
                    region_key=region_key,
                    price_band_key=price_band_key,
                )

                if source_reported_count is None:
                    source_reported_count = page.source_reported_count
                latest_reported_count = page.source_reported_count
                max_reported_count = max(max_reported_count, page.source_reported_count)
                max_page = max(
                    max_page,
                    page.max_page,
                    max(1, math.ceil(max_reported_count / PAGE_SIZE)),
                )
                result_cap_hit = result_cap_hit or max_page >= self.hard_max_pages
                target_pages = min(
                    max_page,
                    self.hard_max_pages,
                    max_page if reconciliation else self.incremental_pages,
                )

                minimum = 0 if page_number == target_pages else math.ceil(PAGE_SIZE * 0.75)
                _validate_page(page, page_number=page_number, expected_minimum=minimum)
                items_by_id.update({item.source_listing_id: item for item in page.items})
                seen_ids.update(item.source_listing_id for item in page.items)
                pages_fetched += 1
                completed_pages += 1
                cards_seen += page.cards_seen
                cards_parsed += page.cards_parsed
                cards_total += page.cards_total
                project_cards_skipped += page.project_cards_skipped
                blank_cards_skipped += page.blank_cards_skipped

                if page_number >= target_pages:
                    break
                page_number += 1
        except SourceChallenge as exc:
            progress = self._progress_cursor(
                region_key=region_key,
                price_band_key=price_band_key,
                resume_page=page_number,
                completed_pages=completed_pages,
                target_pages=target_pages,
                cards_seen=cards_seen,
                cards_parsed=cards_parsed,
                cards_total=cards_total,
                project_cards_skipped=project_cards_skipped,
                blank_cards_skipped=blank_cards_skipped,
                max_page=max_page,
                source_reported_count=source_reported_count,
                latest_reported_count=latest_reported_count,
                max_reported_count=max_reported_count,
                seen_ids=seen_ids,
                identity_history_complete=identity_history_complete,
            )
            challenge = dict(exc.challenge)
            challenge.update(
                {
                    "region_key": region_key,
                    "bundesland": region.label,
                    "price_band_key": price_band_key,
                    "page": page_number,
                    "navigation_url": self._page_url(region_key, price_band_key, page_number),
                }
            )
            raise SourceChallenge(
                str(exc),
                challenge=challenge,
                pages_fetched=pages_fetched,
                items_seen=len(items_by_id),
                source_reported_count=source_reported_count,
                next_cursor=progress,
                partial_items=list(items_by_id.values()),
            ) from exc
        except SourceFetchError as exc:
            progress = self._progress_cursor(
                region_key=region_key,
                price_band_key=price_band_key,
                resume_page=page_number,
                completed_pages=completed_pages,
                target_pages=target_pages,
                cards_seen=cards_seen,
                cards_parsed=cards_parsed,
                cards_total=cards_total,
                project_cards_skipped=project_cards_skipped,
                blank_cards_skipped=blank_cards_skipped,
                max_page=max_page,
                source_reported_count=source_reported_count,
                latest_reported_count=latest_reported_count,
                max_reported_count=max_reported_count,
                seen_ids=seen_ids,
                identity_history_complete=identity_history_complete,
            )
            raise SourceFetchError(
                str(exc),
                pages_fetched=pages_fetched,
                items_seen=len(items_by_id),
                source_reported_count=source_reported_count,
                next_cursor=progress,
                partial_items=list(items_by_id.values()),
                halt_source=exc.halt_source,
            ) from exc
        except Exception as exc:
            progress = self._progress_cursor(
                region_key=region_key,
                price_band_key=price_band_key,
                resume_page=page_number,
                completed_pages=completed_pages,
                target_pages=target_pages,
                cards_seen=cards_seen,
                cards_parsed=cards_parsed,
                cards_total=cards_total,
                project_cards_skipped=project_cards_skipped,
                blank_cards_skipped=blank_cards_skipped,
                max_page=max_page,
                source_reported_count=source_reported_count,
                latest_reported_count=latest_reported_count,
                max_reported_count=max_reported_count,
                seen_ids=seen_ids,
                identity_history_complete=identity_history_complete,
            )
            raise SourceFetchError(
                f"Immowelt shard failed: {type(exc).__name__}: {exc}",
                pages_fetched=pages_fetched,
                items_seen=len(items_by_id),
                source_reported_count=source_reported_count,
                next_cursor=progress,
                partial_items=list(items_by_id.values()),
            ) from exc

        benchmark_count = latest_reported_count or source_reported_count or 0
        count_tolerance = max(3, math.ceil(benchmark_count * 0.01))
        count_delta = len(seen_ids) - benchmark_count
        count_plausible = (
            count_delta == 0 if not benchmark_count else (abs(count_delta) <= count_tolerance)
        )
        coverage_complete = bool(
            reconciliation
            and identity_history_complete
            and not result_cap_hit
            and project_cards_skipped == 0
            and blank_cards_skipped == 0
            and completed_pages == max_page
            and cards_seen == cards_parsed
            and count_plausible
        )
        return SourceBatch(
            items=list(items_by_id.values()),
            next_cursor={
                "newest_ids": list(items_by_id)[:100],
                "discovery_completed_pages": completed_pages,
                "discovery_cards_seen": cards_seen,
                "discovery_cards_parsed": cards_parsed,
                "discovery_cards_total": cards_total,
                "discovery_project_cards_skipped": project_cards_skipped,
                "discovery_blank_cards_skipped": blank_cards_skipped,
                "discovery_max_page": max_page,
                "discovery_initial_reported_count": source_reported_count,
                "discovery_latest_reported_count": latest_reported_count,
                "discovery_max_reported_count": max_reported_count,
                "discovery_unique_ids_seen": len(seen_ids),
                "discovery_identity_history_complete": identity_history_complete,
                "discovery_count_delta": count_delta,
                "discovery_count_tolerance": count_tolerance,
                "region_key": region_key,
                "bundesland": region.label,
                "price_band_key": price_band_key,
                "country_code": "DE",
            },
            source_reported_count=source_reported_count,
            coverage_complete=coverage_complete,
            result_cap_hit=result_cap_hit,
            pages_fetched=pages_fetched,
        )
