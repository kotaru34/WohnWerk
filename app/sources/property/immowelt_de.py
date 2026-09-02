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
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from app.sources.base import (
    PropertySource,
    RawProperty,
    SourceBatch,
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
_EXPOSE_RE = re.compile(r"^/expose/(?P<listing_id>[0-9a-f-]{20,})/?$", re.IGNORECASE)
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


@dataclass(frozen=True, slots=True)
class ImmoweltPage:
    items: list[RawProperty]
    source_reported_count: int
    max_page: int
    cards_seen: int
    cards_parsed: int
    cards_total: int
    project_cards_skipped: int


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
    for card in cards:
        anchor = _node_by_test_id(card, COVERING_LINK_TEST_ID)
        if anchor is None:
            identity_cards_seen += 1
            continue

        raw_href = anchor.attrs.get("href", "")
        if _is_project_expose_url(raw_href):
            # The SERP can show multiple product variants that point at the same
            # project URL. No stable variant identity is exposed, so do not merge
            # those variants into one false listing identity.
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


class ImmoweltGermanyPropertySource(PropertySource):
    """Public-browser Immowelt adapter with no login, challenge solving or detail scraping."""

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
        if response.status >= 400:
            raise RuntimeError(f"Immowelt HTTP {response.status}")
        host = (urlparse(page.url).hostname or "").casefold()
        if host not in {"immowelt.de", "www.immowelt.de"}:
            raise RuntimeError(f"Immowelt redirected off-site: {page.url!r}")

        await page.wait_for_selector("h1", timeout=int(self.timeout_seconds * 1000))
        try:
            await page.wait_for_selector(
                f'[data-testid="{CARD_TEST_ID}"]',
                timeout=min(8000, int(self.timeout_seconds * 1000)),
            )
        except PlaywrightTimeoutError:
            # A genuinely empty result set has no cards. The parser/validator below
            # remains authoritative; this wait only prevents reading a partially
            # hydrated non-empty SERP immediately after client-side navigation.
            pass
        await page.wait_for_timeout(500)

        _validate_search_state(url, page.url)

        html = await page.content()
        lowered = html.casefold()
        if (
            "captcha" in lowered
            or "access denied" in lowered
            or "ich bin kein roboter" in lowered
        ):
            raise RuntimeError("Immowelt presented an access challenge; crawler stopped")
        return html, page.url

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        del cursor
        region_key = str(shard.params.get("region_key") or "")
        price_band_key = str(shard.params.get("price_band_key") or "")
        self._page_url(region_key, price_band_key, 1)

        items_by_id: dict[str, RawProperty] = {}
        pages_fetched = 0
        cards_seen = 0
        cards_parsed = 0
        cards_total = 0
        project_cards_skipped = 0
        source_reported_count: int | None = None
        latest_reported_count: int | None = None
        max_reported_count = 0
        max_page = 1
        result_cap_hit = False

        try:
            first_html, first_url = await self._load_html(
                self._page_url(region_key, price_band_key, 1)
            )
            first = parse_immowelt_search_page(
                first_html,
                page_url=first_url,
                region_key=region_key,
                price_band_key=price_band_key,
            )
            _validate_page(first, page_number=1, expected_minimum=0)

            source_reported_count = first.source_reported_count
            latest_reported_count = first.source_reported_count
            max_reported_count = first.source_reported_count
            max_page = first.max_page
            result_cap_hit = max_page >= self.hard_max_pages
            target_pages = min(
                max_page,
                self.hard_max_pages,
                max_page if reconciliation else self.incremental_pages,
            )
            items_by_id.update({item.source_listing_id: item for item in first.items})
            pages_fetched = 1
            cards_seen = first.cards_seen
            cards_parsed = first.cards_parsed
            cards_total = first.cards_total
            project_cards_skipped = first.project_cards_skipped

            page_number = 2
            while page_number <= target_pages:
                page_html, page_url = await self._load_html(
                    self._page_url(region_key, price_band_key, page_number)
                )
                page = parse_immowelt_search_page(
                    page_html,
                    page_url=page_url,
                    region_key=region_key,
                    price_band_key=price_band_key,
                )
                latest_reported_count = page.source_reported_count
                max_reported_count = max(max_reported_count, page.source_reported_count)
                max_page = max(
                    max_page,
                    page.max_page,
                    max(1, math.ceil(max_reported_count / PAGE_SIZE)),
                )
                result_cap_hit = result_cap_hit or max_page >= self.hard_max_pages
                if reconciliation:
                    target_pages = min(max_page, self.hard_max_pages)

                minimum = 0 if page_number == target_pages else math.ceil(PAGE_SIZE * 0.75)
                _validate_page(page, page_number=page_number, expected_minimum=minimum)
                items_by_id.update({item.source_listing_id: item for item in page.items})
                pages_fetched += 1
                cards_seen += page.cards_seen
                cards_parsed += page.cards_parsed
                cards_total += page.cards_total
                project_cards_skipped += page.project_cards_skipped
                page_number += 1
        except Exception as exc:
            if isinstance(exc, SourceFetchError):
                raise
            raise SourceFetchError(
                f"Immowelt shard failed: {type(exc).__name__}: {exc}",
                pages_fetched=pages_fetched,
                items_seen=len(items_by_id),
                source_reported_count=source_reported_count,
                next_cursor={
                    "discovery_cards_seen": cards_seen,
                    "discovery_cards_parsed": cards_parsed,
                    "discovery_cards_total": cards_total,
                    "discovery_project_cards_skipped": project_cards_skipped,
                    "discovery_max_page": max_page,
                    "discovery_latest_reported_count": latest_reported_count,
                    "discovery_max_reported_count": max_reported_count,
                },
                partial_items=list(items_by_id.values()),
            ) from exc

        benchmark_count = latest_reported_count or source_reported_count or 0
        count_tolerance = max(3, math.ceil(benchmark_count * 0.01))
        count_delta = len(items_by_id) - benchmark_count
        count_plausible = (
            count_delta == 0 if not benchmark_count else (abs(count_delta) <= count_tolerance)
        )
        coverage_complete = bool(
            reconciliation
            and not result_cap_hit
            and project_cards_skipped == 0
            and pages_fetched == max_page
            and cards_seen == cards_parsed
            and count_plausible
        )
        return SourceBatch(
            items=list(items_by_id.values()),
            next_cursor={
                "newest_ids": list(items_by_id)[:100],
                "discovery_cards_seen": cards_seen,
                "discovery_cards_parsed": cards_parsed,
                "discovery_cards_total": cards_total,
                "discovery_project_cards_skipped": project_cards_skipped,
                "discovery_max_page": max_page,
                "discovery_initial_reported_count": source_reported_count,
                "discovery_latest_reported_count": latest_reported_count,
                "discovery_max_reported_count": max_reported_count,
                "discovery_count_delta": count_delta,
                "discovery_count_tolerance": count_tolerance,
                "country_code": "DE",
            },
            source_reported_count=source_reported_count,
            coverage_complete=coverage_complete,
            result_cap_hit=result_cap_hit,
            pages_fetched=pages_fetched,
        )