from __future__ import annotations

import asyncio
import hashlib
import math
import random
import re
from dataclasses import dataclass
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

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
    GERMANY_PROPERTY_MAX_PRICE_EUR,
    GERMANY_PROPERTY_MIN_PRICE_EUR,
    REGIONS_BY_KEY,
)
from app.sources.property.immmo import _clean_text, _decimal

BASE_URL = "https://www.von-poll.com"
PAGE_SIZE = 20
DEFAULT_INCREMENTAL_PAGES = 2
DEFAULT_HARD_MAX_PAGES = 100

_EXPOSE_RE = re.compile(r"^/de/expose/[^/]+/(?P<slug>[^/?#]+?)/?$", re.IGNORECASE)
_PROVIDER_ID_RE = re.compile(r"-(?P<id>\d{6,})$")
_COUNT_RE = re.compile(
    r"(?P<start>[\d.]+)\s*[–-]\s*(?P<end>[\d.]+)\s+von\s+"
    r"(?P<count>[\d.]+)\s+Treffer",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(r"(?P<price>[\d.]+(?:,\d{1,2})?)\s*EUR\s*$", re.IGNORECASE)
_ROOM_AREA_RE = re.compile(
    r"(?P<rooms>[\d.,]+)\s*Zi\.\s*"
    r"(?:ca\.\s*)?(?P<living>[\d.]+(?:,\d+)?)\s*m(?:²|2)\s*"
    r"(?:ca\.\s*)?(?P<plot>[\d.]+(?:,\d+)?)\s*m(?:²|2)",
    re.IGNORECASE,
)
_ROOM_RE = re.compile(r"(?P<rooms>[\d.,]+)\s*Zi\.", re.IGNORECASE)
_STATUS_RE = re.compile(r"^(?P<status>Reserviert|Verkauft)\s*-\s*", re.IGNORECASE)
_ALLOWED_HOSTS = {"von-poll.com", "www.von-poll.com"}
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


@dataclass(frozen=True, slots=True)
class VonPollPage:
    items: list[RawProperty]
    source_reported_count: int
    max_page: int
    cards_seen: int
    cards_parsed: int
    unavailable_cards: int
    out_of_budget_cards: int
    unstable_identity_cards: int


@dataclass(slots=True)
class _Anchor:
    href: str
    parts: list[str]


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[_Anchor] = []
        self.page_text: list[str] = []
        self._current: _Anchor | None = None
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1
        if tag == "a":
            href = attributes.get("href", "")
            if _EXPOSE_RE.match(urlparse(urljoin(BASE_URL, href)).path):
                self._current = _Anchor(href=href, parts=[])

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "a" and self._current is not None:
            self.anchors.append(self._current)
            self._current = None
        if tag in {"script", "style", "noscript", "template"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        value = _clean_text(data)
        if not value:
            return
        self.page_text.append(value)
        if self._current is not None:
            self._current.parts.append(value)


def _canonical_expose_url(href: str) -> tuple[str, str] | None:
    absolute = urljoin(BASE_URL, href)
    parsed = urlparse(absolute)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or host not in _ALLOWED_HOSTS:
        return None
    match = _EXPOSE_RE.match(parsed.path)
    if match is None:
        return None
    slug = match.group("slug").strip().casefold()
    canonical = urlunparse(("https", "www.von-poll.com", parsed.path.rstrip("/"), "", "", ""))
    provider = _PROVIDER_ID_RE.search(slug)
    listing_id = (
        provider.group("id")
        if provider is not None
        else "url-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    )
    return canonical, listing_id


def _count_and_pages(text: str) -> tuple[int, int]:
    match = _COUNT_RE.search(text)
    if match is None:
        raise ValueError("VON POLL result count is missing")
    count = int(match.group("count").replace(".", ""))
    return count, max(1, math.ceil(count / PAGE_SIZE))


def _parse_card_text(
    text: str,
    *,
    region_key: str,
) -> tuple[str, str, str, str | None, Decimal | None, Decimal | None, Decimal | None] | None:
    region = REGIONS_BY_KEY[region_key]
    normalized = _clean_text(text)
    location = re.match(
        rf"^(?:\d{{1,3}}\s+)*(?P<postal>\d{{5}})\s+(?P<city>.+?)\s+[–-]\s+"
        rf"{re.escape(region.label)}\s+(?P<rest>.+)$",
        normalized,
        re.IGNORECASE,
    )
    if location is None:
        return None

    rest = location.group("rest").strip()
    status_match = _STATUS_RE.match(rest)
    status = status_match.group("status").casefold() if status_match else None
    if status_match:
        rest = rest[status_match.end() :].strip()

    price_match = _PRICE_RE.search(rest)
    price = _decimal(price_match.group("price")) if price_match else None
    before_price = rest[: price_match.start()].strip() if price_match else rest

    areas = _ROOM_AREA_RE.search(before_price)
    living = _decimal(areas.group("living")) if areas else None
    plot = _decimal(areas.group("plot")) if areas else None
    title_end = areas.start() if areas else None
    if title_end is None:
        room = _ROOM_RE.search(before_price)
        title_end = room.start() if room else len(before_price)
    title = before_price[:title_end].strip(" -–") or "Haus zum Kauf"

    return (
        location.group("postal"),
        location.group("city").strip(),
        title,
        status,
        price,
        living,
        plot,
    )


def parse_von_poll_search_page(
    html: str,
    *,
    page_url: str,
    region_key: str,
) -> VonPollPage:
    if region_key not in REGIONS_BY_KEY:
        raise ValueError(f"Unknown German region: {region_key!r}")

    parser = _ListingParser()
    parser.feed(html)
    page_text = _clean_text(" ".join(parser.page_text))
    source_reported_count, max_page = _count_and_pages(page_text)

    items: list[RawProperty] = []
    cards_seen = 0
    cards_parsed = 0
    unavailable_cards = 0
    out_of_budget_cards = 0
    unstable_identity_cards = 0
    seen_urls: set[str] = set()

    for anchor in parser.anchors:
        detail = _canonical_expose_url(anchor.href)
        if detail is None:
            continue
        url, listing_id = detail
        if url in seen_urls:
            continue
        seen_urls.add(url)
        cards_seen += 1
        if listing_id.startswith("url-"):
            unstable_identity_cards += 1

        facts = _parse_card_text(" ".join(anchor.parts), region_key=region_key)
        if facts is None:
            continue
        cards_parsed += 1
        postal_code, city, title, status, price, living, plot = facts

        if status in {"verkauft", "reserviert"}:
            unavailable_cards += 1
            continue
        if price is not None and (
            price < GERMANY_PROPERTY_MIN_PRICE_EUR
            or price > GERMANY_PROPERTY_MAX_PRICE_EUR
        ):
            out_of_budget_cards += 1
            continue

        items.append(
            RawProperty(
                source_listing_id=listing_id,
                url=url,
                title=title[:500],
                description=None,
                price_eur=price,
                living_area_m2=living,
                plot_area_m2=plot,
                postal_code=postal_code,
                city=city,
                raw_payload={
                    "format": "von-poll-public-search-v1",
                    "country_code": "DE",
                    "discovery_url": page_url,
                    "region_key": region_key,
                    "source_postal_code": postal_code,
                    "source_status": status or "available",
                    "identity_stable": not listing_id.startswith("url-"),
                },
            )
        )

    return VonPollPage(
        items=items,
        source_reported_count=source_reported_count,
        max_page=max_page,
        cards_seen=cards_seen,
        cards_parsed=cards_parsed,
        unavailable_cards=unavailable_cards,
        out_of_budget_cards=out_of_budget_cards,
        unstable_identity_cards=unstable_identity_cards,
    )


def _validate_page(page: VonPollPage, *, page_number: int) -> None:
    if page.source_reported_count and page.cards_seen == 0:
        raise RuntimeError(f"VON POLL returned no property cards on non-empty page {page_number}")
    if page.cards_seen != page.cards_parsed:
        raise RuntimeError(
            f"VON POLL card parsing incomplete on page {page_number}: "
            f"parsed {page.cards_parsed}/{page.cards_seen} expose cards"
        )


class VonPollGermanyPropertySource(PropertySource):
    """Low-rate crawler for VON POLL's public German house-sale inventory."""

    name = "von-poll-de"

    def __init__(
        self,
        *,
        request_delay_seconds: float = 3.0,
        incremental_pages: int = DEFAULT_INCREMENTAL_PAGES,
        hard_max_pages: int = DEFAULT_HARD_MAX_PAGES,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.request_delay_seconds = max(2.0, request_delay_seconds)
        self.incremental_pages = max(1, incremental_pages)
        self.hard_max_pages = max(10, hard_max_pages)
        self.timeout_seconds = timeout_seconds
        self._requests_made = 0

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=region.key,
                params={"region_key": region.key},
                result_cap=self.hard_max_pages * PAGE_SIZE,
            )
            for region in GERMAN_REGIONS
        ]

    @staticmethod
    def _page_url(region_key: str, page: int) -> str:
        if region_key not in REGIONS_BY_KEY:
            raise ValueError(f"Unknown German region: {region_key!r}")
        base = f"{BASE_URL}/de/haus-kaufen/{region_key}"
        return base if page == 1 else f"{base}?page={page}"

    async def _sleep(self) -> None:
        await asyncio.sleep(self.request_delay_seconds * random.uniform(0.85, 1.2))

    async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        if self._requests_made:
            await self._sleep()
        self._requests_made += 1

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await client.get(url)
                host = (response.url.host or "").casefold()
                if host not in _ALLOWED_HOSTS:
                    raise RuntimeError(f"VON POLL redirected off-site: {response.url!s}")
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                if status in {401, 403}:
                    raise SourceFetchError(
                        f"VON POLL access gate HTTP {status}",
                        halt_source=True,
                    ) from exc
                if attempt == 2 or status not in _RETRYABLE_STATUSES:
                    raise
                await asyncio.sleep(2**attempt)
            except (httpx.HTTPError, RuntimeError) as exc:
                last_error = exc
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)
        raise RuntimeError("unreachable") from last_error

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        del cursor
        region_key = str(shard.params.get("region_key") or "")
        self._page_url(region_key, 1)

        items_by_id: dict[str, RawProperty] = {}
        pages_fetched = 0
        cards_seen = 0
        cards_parsed = 0
        unavailable_cards = 0
        out_of_budget_cards = 0
        unstable_identity_cards = 0
        source_reported_count: int | None = None
        max_page = 1
        result_cap_hit = False

        headers = {
            "User-Agent": "WohnWerk/0.4 (+private self-hosted German property search)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        }

        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=self.timeout_seconds,
                follow_redirects=True,
            ) as client:
                first_url = self._page_url(region_key, 1)
                first_response = await self._get(client, first_url)
                first = parse_von_poll_search_page(
                    first_response.text,
                    page_url=str(first_response.url),
                    region_key=region_key,
                )
                _validate_page(first, page_number=1)
                source_reported_count = first.source_reported_count
                max_page = first.max_page
                result_cap_hit = max_page > self.hard_max_pages
                target_pages = min(
                    max_page,
                    self.hard_max_pages,
                    max_page if reconciliation else self.incremental_pages,
                )

                pages_fetched = 1
                cards_seen = first.cards_seen
                cards_parsed = first.cards_parsed
                unavailable_cards = first.unavailable_cards
                out_of_budget_cards = first.out_of_budget_cards
                unstable_identity_cards = first.unstable_identity_cards
                items_by_id.update({item.source_listing_id: item for item in first.items})

                for page_number in range(2, target_pages + 1):
                    response = await self._get(client, self._page_url(region_key, page_number))
                    page = parse_von_poll_search_page(
                        response.text,
                        page_url=str(response.url),
                        region_key=region_key,
                    )
                    _validate_page(page, page_number=page_number)
                    # Count/page total may drift while a long reconciliation is running.
                    max_page = max(max_page, page.max_page)
                    result_cap_hit = result_cap_hit or max_page > self.hard_max_pages
                    items_by_id.update({item.source_listing_id: item for item in page.items})
                    pages_fetched += 1
                    cards_seen += page.cards_seen
                    cards_parsed += page.cards_parsed
                    unavailable_cards += page.unavailable_cards
                    out_of_budget_cards += page.out_of_budget_cards
                    unstable_identity_cards += page.unstable_identity_cards
        except Exception as exc:
            if isinstance(exc, SourceFetchError):
                exc.pages_fetched = pages_fetched
                exc.items_seen = len(items_by_id)
                exc.source_reported_count = source_reported_count
                exc.partial_items = list(items_by_id.values())
                exc.next_cursor = {
                    "discovery_cards_seen": cards_seen,
                    "discovery_cards_parsed": cards_parsed,
                    "discovery_unavailable_cards": unavailable_cards,
                    "discovery_out_of_budget_cards": out_of_budget_cards,
                    "discovery_unstable_identity_cards": unstable_identity_cards,
                    "country_code": "DE",
                }
                raise
            raise SourceFetchError(
                f"VON POLL shard failed: {type(exc).__name__}: {exc}",
                pages_fetched=pages_fetched,
                items_seen=len(items_by_id),
                source_reported_count=source_reported_count,
                partial_items=list(items_by_id.values()),
                next_cursor={
                    "discovery_cards_seen": cards_seen,
                    "discovery_cards_parsed": cards_parsed,
                    "discovery_unavailable_cards": unavailable_cards,
                    "discovery_out_of_budget_cards": out_of_budget_cards,
                    "discovery_unstable_identity_cards": unstable_identity_cards,
                    "country_code": "DE",
                },
            ) from exc

        coverage_complete = bool(
            reconciliation
            and not result_cap_hit
            and pages_fetched >= max_page
            and cards_seen == cards_parsed
            and unstable_identity_cards == 0
        )
        return SourceBatch(
            items=list(items_by_id.values()),
            next_cursor={
                "newest_ids": list(items_by_id)[:100],
                "discovery_cards_seen": cards_seen,
                "discovery_cards_parsed": cards_parsed,
                "discovery_unavailable_cards": unavailable_cards,
                "discovery_out_of_budget_cards": out_of_budget_cards,
                "discovery_unstable_identity_cards": unstable_identity_cards,
                "discovery_max_page": max_page,
                "country_code": "DE",
            },
            source_reported_count=source_reported_count,
            coverage_complete=coverage_complete,
            result_cap_hit=result_cap_hit,
            pages_fetched=pages_fetched,
        )
