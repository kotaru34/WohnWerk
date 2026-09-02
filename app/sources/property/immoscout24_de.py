from __future__ import annotations

import asyncio
import json
import math
import random
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode

import httpx

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
from app.sources.property.immmo import _clean_text, _decimal

BASE_URL = "https://www.immobilienscout24.de"
PAGE_SIZE = 20
DEFAULT_HARD_MAX_PAGES = 250
_CONTEXT_RE = re.compile(r'"heyImmoContext"\s*:\s*("(?:\\.|[^"\\])*")')
_TOTAL_RE = re.compile(r"(?P<count>[\d.]+)")


@dataclass(frozen=True, slots=True)
class ImmoScoutPage:
    items: list[RawProperty]
    source_reported_count: int
    max_page: int
    cards_seen: int
    cards_parsed: int


class _PageChromeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headline_parts: list[str] = []
        self.pages: list[int] = []
        self._headline_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if self._headline_depth:
            self._headline_depth += 1
        elif attributes.get("data-testid") == "ResultListHeadline":
            self._headline_depth = 1

        if attributes.get("data-testid") == "pagination-button":
            try:
                self.pages.append(int(attributes.get("page") or ""))
            except ValueError:
                pass

    def handle_endtag(self, tag: str) -> None:
        del tag
        if self._headline_depth:
            self._headline_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._headline_depth:
            self.headline_parts.append(data)


def _decode_context(html: str) -> dict[str, Any]:
    match = _CONTEXT_RE.search(html)
    if match is None:
        raise ValueError("ImmoScout24 public search context is missing")
    outer = json.loads(match.group(1))
    decoded = json.loads(outer)
    if not isinstance(decoded, dict):
        raise TypeError("ImmoScout24 search context is not an object")
    return decoded


def _reported_count_and_pages(html: str) -> tuple[int, int]:
    parser = _PageChromeParser()
    parser.feed(html)
    headline = _clean_text(" ".join(parser.headline_parts))
    match = _TOTAL_RE.search(headline)
    if match is None:
        raise ValueError("ImmoScout24 result count is missing")
    count = int(match.group("count").replace(".", ""))
    calculated = max(1, math.ceil(count / PAGE_SIZE))
    return count, max([calculated, *parser.pages])


def parse_immoscout24_search_page(
    html: str,
    *,
    page_url: str,
    region_key: str,
    price_band_key: str,
) -> ImmoScoutPage:
    context = _decode_context(html)
    raw_items = context.get("search_result_list")
    if not isinstance(raw_items, list):
        raise TypeError("ImmoScout24 result list is missing")

    source_reported_count, max_page = _reported_count_and_pages(html)
    items: list[RawProperty] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        listing_id = str(raw.get("expose_id") or "").strip()
        if not listing_id.isdigit():
            continue

        address = raw.get("address") if isinstance(raw.get("address"), dict) else {}
        postal_code = str(address.get("postcode") or "").strip()
        if not (len(postal_code) == 5 and postal_code.isdigit()):
            postal_code = None
        city = _clean_text(str(address.get("city") or "")) or None
        title = _clean_text(str(raw.get("title") or "")) or f"Haus zum Kauf {listing_id}"

        items.append(
            RawProperty(
                source_listing_id=listing_id,
                url=f"{BASE_URL}/expose/{listing_id}",
                title=title[:500],
                description=None,
                price_eur=_decimal(str(raw.get("price") or "")),
                living_area_m2=_decimal(str(raw.get("living_space") or "")),
                plot_area_m2=_decimal(str(raw.get("ground_area") or "")),
                postal_code=postal_code,
                city=city,
                raw_payload={
                    "format": "immoscout24-public-search-v1",
                    "country_code": "DE",
                    "discovery_url": page_url,
                    "region_key": region_key,
                    "price_band_key": price_band_key,
                    "source_postal_code": postal_code,
                    "identity_stable": True,
                },
            )
        )

    return ImmoScoutPage(
        items=items,
        source_reported_count=source_reported_count,
        max_page=max_page,
        cards_seen=len(raw_items),
        cards_parsed=len(items),
    )


def _validate_page(page: ImmoScoutPage, *, page_number: int, expected_minimum: int) -> None:
    if page.source_reported_count and page.cards_seen == 0:
        raise RuntimeError(f"ImmoScout24 returned no cards on non-empty page {page_number}")
    if page.cards_seen != page.cards_parsed:
        raise RuntimeError(
            f"ImmoScout24 card parsing incomplete on page {page_number}: "
            f"parsed {page.cards_parsed}/{page.cards_seen} cards"
        )
    if expected_minimum and page.cards_seen < expected_minimum:
        raise RuntimeError(
            f"ImmoScout24 page {page_number} unexpectedly short: "
            f"saw {page.cards_seen}, expected at least {expected_minimum}"
        )


class ImmoScout24GermanyPropertySource(PropertySource):
    """Low-rate public ImmoScout24 house-search adapter for WohnWerk's DE budget."""

    name = "immoscout24-de"

    def __init__(
        self,
        *,
        request_delay_seconds: float = 1.5,
        incremental_pages: int = 2,
        hard_max_pages: int = DEFAULT_HARD_MAX_PAGES,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.request_delay_seconds = max(1.0, request_delay_seconds)
        self.incremental_pages = max(1, incremental_pages)
        self.hard_max_pages = max(10, hard_max_pages)
        self.timeout_seconds = timeout_seconds
        self._requests_made = 0

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

    async def _sleep(self) -> None:
        await asyncio.sleep(self.request_delay_seconds * random.uniform(0.8, 1.25))

    async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        if self._requests_made:
            await self._sleep()
        self._requests_made += 1
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await client.get(url)
                response.raise_for_status()
                host = (response.url.host or "").casefold()
                if host not in {"immobilienscout24.de", "www.immobilienscout24.de"}:
                    raise RuntimeError(
                        "ImmoScout24 redirected off-site: "
                        f"requested={url!r} final={str(response.url)!r}"
                    )
                return response
            except (httpx.HTTPError, RuntimeError) as exc:
                last_error = exc
                status = (
                    exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                )
                if attempt == 2 or (status is not None and status not in {429, 500, 502, 503, 504}):
                    raise
                await asyncio.sleep(2**attempt)
        raise RuntimeError("unreachable") from last_error

    @staticmethod
    def _page_url(region_key: str, price_band_key: str, page: int) -> str:
        region = REGIONS_BY_KEY.get(region_key)
        band = PRICE_BANDS_BY_KEY.get(price_band_key)
        if region is None or band is None:
            raise ValueError(
                f"Invalid ImmoScout24 shard: region={region_key!r} band={price_band_key!r}"
            )
        query = urlencode(
            {
                "price": f"{band.minimum_eur}-{band.maximum_eur}.0",
                "sorting": "2",
                "pagenumber": page,
            }
        )
        return f"{BASE_URL}/Suche/de/{region.immoscout_slug}/haus-kaufen?{query}"

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
        # Validate before opening a client or making any request.
        self._page_url(region_key, price_band_key, 1)

        headers = {
            "User-Agent": "WohnWerk/0.4 (+private self-hosted German property search)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        }
        items_by_id: dict[str, RawProperty] = {}
        pages_fetched = 0
        cards_seen = 0
        cards_parsed = 0
        source_reported_count: int | None = None
        latest_reported_count: int | None = None
        max_reported_count = 0
        max_page = 1
        result_cap_hit = False

        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=self.timeout_seconds,
                follow_redirects=True,
            ) as client:
                first_url = self._page_url(region_key, price_band_key, 1)
                first_response = await self._get(client, first_url)
                first = parse_immoscout24_search_page(
                    first_response.text,
                    page_url=str(first_response.url),
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

                page_number = 2
                while page_number <= target_pages:
                    page_url = self._page_url(region_key, price_band_key, page_number)
                    response = await self._get(client, page_url)
                    page = parse_immoscout24_search_page(
                        response.text,
                        page_url=str(response.url),
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
                    page_number += 1
        except Exception as exc:
            if isinstance(exc, SourceFetchError):
                raise
            raise SourceFetchError(
                f"ImmoScout24 shard failed: {type(exc).__name__}: {exc}",
                pages_fetched=pages_fetched,
                items_seen=len(items_by_id),
                source_reported_count=source_reported_count,
                next_cursor={
                    "discovery_cards_seen": cards_seen,
                    "discovery_cards_parsed": cards_parsed,
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
