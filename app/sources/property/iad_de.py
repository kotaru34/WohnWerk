from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
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
    GERMANY_PROPERTY_MAX_PRICE_EUR,
    GERMANY_PROPERTY_MIN_PRICE_EUR,
)
from app.sources.property.immmo import _clean_text, _decimal, _DOMParser, _Node
from app.sources.property.preview import card_thumbnail_url

BASE_URL = "https://iad-immobilien.de"
SEARCH_ROOT = f"{BASE_URL}/immobilien/haeuser"
DEFAULT_FRONTIER_PAGES = 8
DEFAULT_HARD_MAX_PAGES = 40

_ALLOWED_HOSTS = {"iad-immobilien.de", "www.iad-immobilien.de"}
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_DETAIL_PATH_RE = re.compile(
    r"^/immobilien/(?P<slug>[a-z0-9][a-z0-9-]*-kauf-(?P<listing_id>[a-z0-9-]+))/?$",
    re.IGNORECASE,
)
_COUNT_RE = re.compile(r"(?P<count>[\d.]+)\s+Immobilien\s+gefunden", re.IGNORECASE)
_LOCATION_RE = re.compile(r"\b(?P<plz>\d{5})\s+(?P<city>[A-ZÄÖÜ][^|€]{1,100}?)\b")
_PRICE_RE = re.compile(
    r"\bKaufpreis:\s*(?P<price>[\d.]+(?:,\d{1,2})?)\s*€",
    re.IGNORECASE,
)
_LIVING_RE = re.compile(
    r"\bWohnfläche:\s*(?:ca\.?\s*)?(?P<area>[\d.,]+)\s*m(?:²|2)",
    re.IGNORECASE,
)
_PLOT_RE = re.compile(
    r"\bGrundstücksfläche:\s*(?:ca\.?\s*)?(?P<area>[\d.,]+)\s*m(?:²|2)",
    re.IGNORECASE,
)
_UNAVAILABLE_RE = re.compile(r"\b(?:verkauft|reserviert)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class IadPage:
    items: list[RawProperty]
    source_reported_count: int | None
    cards_seen: int
    cards_parsed: int
    unavailable_cards: int
    price_unknown_cards: int
    out_of_budget_cards: int


def _canonical_detail(value: str, *, page_url: str) -> tuple[str, str] | None:
    absolute = urljoin(page_url, value)
    parsed = urlparse(absolute)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or host not in _ALLOWED_HOSTS:
        return None
    match = _DETAIL_PATH_RE.match(parsed.path)
    if match is None:
        return None
    canonical = urlunparse(("https", "iad-immobilien.de", parsed.path.rstrip("/"), "", "", ""))
    return canonical, match.group("listing_id").upper()


def _detail_anchors(node: _Node, *, page_url: str) -> list[tuple[_Node, str, str]]:
    result: list[tuple[_Node, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for child in node.walk():
        if child.tag != "a":
            continue
        detail = _canonical_detail(child.attrs.get("href", ""), page_url=page_url)
        if detail is None:
            continue
        url, listing_id = detail
        key = (url, _clean_text(child.text()))
        if key in seen:
            continue
        seen.add(key)
        result.append((child, url, listing_id))
    return result


def _source_location(node: _Node) -> re.Match[str] | None:
    candidates: list[tuple[int, re.Match[str]]] = []
    for child in node.walk():
        direct = _clean_text(" ".join(child.text_parts))
        match = _LOCATION_RE.match(direct)
        if match is not None:
            candidates.append((len(direct), match))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _card_for_anchor(anchor: _Node, *, listing_id: str) -> _Node | None:
    node = anchor.parent
    fallback: _Node | None = None
    marker = listing_id.casefold()
    for _ in range(16):
        if node is None or node.tag == "document":
            break
        text = node.text()
        links = [
            child.attrs.get("href", "").casefold()
            for child in node.walk()
            if child.tag == "a"
        ]
        matching_links = sum(marker in href for href in links)
        if matching_links and _PRICE_RE.search(text) and _source_location(node):
            fallback = node
            if _LIVING_RE.search(text) or "Haus zu kaufen" in text:
                return node
        node = node.parent
    return fallback


def _title_for_card(card: _Node, *, page_url: str, listing_id: str) -> str:
    values = [
        _clean_text(anchor.text())
        for anchor, _url, candidate_id in _detail_anchors(card, page_url=page_url)
        if candidate_id == listing_id and 6 <= len(_clean_text(anchor.text())) <= 500
    ]
    return max(values, key=len, default="")


def parse_iad_search_page(html: str, *, page_url: str) -> IadPage:
    parser = _DOMParser()
    parser.feed(html)
    page_text = parser.root.text()

    count_match = _COUNT_RE.search(page_text)
    source_reported_count = (
        int(count_match.group("count").replace(".", "")) if count_match else None
    )

    candidates: list[tuple[_Node, str, str]] = []
    seen_ids: set[str] = set()
    for anchor, url, listing_id in _detail_anchors(parser.root, page_url=page_url):
        if listing_id in seen_ids:
            continue
        card = _card_for_anchor(anchor, listing_id=listing_id)
        if card is None:
            continue
        seen_ids.add(listing_id)
        candidates.append((card, url, listing_id))

    items_by_id: dict[str, RawProperty] = {}
    cards_parsed = unavailable_cards = price_unknown_cards = out_of_budget_cards = 0

    for card, url, listing_id in candidates:
        text = card.text()
        location = _source_location(card)
        title = _title_for_card(card, page_url=page_url, listing_id=listing_id)
        if location is None or not title:
            continue
        cards_parsed += 1

        if _UNAVAILABLE_RE.search(text):
            unavailable_cards += 1
            continue
        price_match = _PRICE_RE.search(text)
        price = _decimal(price_match.group("price")) if price_match else None
        if price is None:
            price_unknown_cards += 1
            continue
        if (
            price < GERMANY_PROPERTY_MIN_PRICE_EUR
            or price > GERMANY_PROPERTY_MAX_PRICE_EUR
        ):
            out_of_budget_cards += 1
            continue

        living_match = _LIVING_RE.search(text)
        plot_match = _PLOT_RE.search(text)
        city = _clean_text(location.group("city")).strip(" ,-")[:100]
        thumbnail_url = card_thumbnail_url(card, page_url=page_url)
        items_by_id[listing_id] = RawProperty(
            source_listing_id=listing_id,
            url=url,
            title=title[:500],
            price_eur=price,
            living_area_m2=(
                _decimal(living_match.group("area")) if living_match else None
            ),
            plot_area_m2=(
                _decimal(plot_match.group("area")) if plot_match else None
            ),
            postal_code=location.group("plz"),
            city=city or None,
            raw_payload={
                "format": "iad-de-public-frontier-v1",
                "country_code": "DE",
                "discovery_url": page_url,
                "source_location": f"{location.group('plz')} {city}".strip(),
                "identity_stable": True,
                "frontier_only": True,
                **(
                    {
                        "thumbnail_url": thumbnail_url,
                        "thumbnail_semantics": "source_search_card",
                    }
                    if thumbnail_url
                    else {}
                ),
            },
        )

    return IadPage(
        items=list(items_by_id.values()),
        source_reported_count=source_reported_count,
        cards_seen=len(candidates),
        cards_parsed=cards_parsed,
        unavailable_cards=unavailable_cards,
        price_unknown_cards=price_unknown_cards,
        out_of_budget_cards=out_of_budget_cards,
    )


def _validate_page(page: IadPage, *, page_number: int) -> None:
    if page.source_reported_count and page.cards_seen == 0:
        raise RuntimeError(f"iad returned no identifiable cards on non-empty page {page_number}")
    if page.cards_seen != page.cards_parsed:
        raise RuntimeError(
            f"iad card parsing incomplete on page {page_number}: "
            f"parsed {page.cards_parsed}/{page.cards_seen}"
        )


class IadGermanyPropertySource(PropertySource):
    """Bounded public iad Germany house frontier."""

    name = "iad-de"

    def __init__(
        self,
        *,
        request_delay_seconds: float = 3.0,
        frontier_pages: int = DEFAULT_FRONTIER_PAGES,
        hard_max_pages: int = DEFAULT_HARD_MAX_PAGES,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.request_delay_seconds = max(2.0, request_delay_seconds)
        self.frontier_pages = max(1, frontier_pages)
        self.hard_max_pages = max(self.frontier_pages, hard_max_pages)
        self.timeout_seconds = timeout_seconds
        self._requests_made = 0

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key="de-public-frontier",
                params={"country_code": "DE"},
                result_cap=self.hard_max_pages * 12,
                priority=75,
            )
        ]

    @staticmethod
    def _page_url(page: int) -> str:
        if page <= 1:
            return SEARCH_ROOT
        return f"{SEARCH_ROOT}?__yPage={page}"

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
                    raise RuntimeError(f"iad redirected off-site: {response.url!s}")
                if response.status_code in {401, 403}:
                    raise SourceFetchError(
                        f"iad access gate HTTP {response.status_code}",
                        halt_source=True,
                    )
                response.raise_for_status()
                return response
            except SourceFetchError:
                raise
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if attempt == 2 or exc.response.status_code not in _RETRYABLE_STATUSES:
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
        del shard, cursor, reconciliation
        items_by_id: dict[str, RawProperty] = {}
        pages_fetched = cards_seen = cards_parsed = 0
        unavailable_cards = price_unknown_cards = out_of_budget_cards = 0
        source_reported_count: int | None = None
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
                for page_number in range(1, self.frontier_pages + 1):
                    response = await self._get(client, self._page_url(page_number))
                    page = parse_iad_search_page(response.text, page_url=str(response.url))
                    _validate_page(page, page_number=page_number)
                    source_reported_count = max(
                        source_reported_count or 0,
                        page.source_reported_count or 0,
                    ) or None
                    items_by_id.update(
                        {item.source_listing_id: item for item in page.items}
                    )
                    pages_fetched += 1
                    cards_seen += page.cards_seen
                    cards_parsed += page.cards_parsed
                    unavailable_cards += page.unavailable_cards
                    price_unknown_cards += page.price_unknown_cards
                    out_of_budget_cards += page.out_of_budget_cards
        except Exception as exc:
            if isinstance(exc, SourceFetchError):
                exc.pages_fetched = pages_fetched
                exc.items_seen = len(items_by_id)
                exc.source_reported_count = source_reported_count
                exc.partial_items = list(items_by_id.values())
                exc.next_cursor = {
                    "country_code": "DE",
                    "frontier_cards_seen": cards_seen,
                    "frontier_cards_parsed": cards_parsed,
                }
                raise
            raise SourceFetchError(
                f"iad frontier failed: {type(exc).__name__}: {exc}",
                pages_fetched=pages_fetched,
                items_seen=len(items_by_id),
                source_reported_count=source_reported_count,
                partial_items=list(items_by_id.values()),
                next_cursor={
                    "country_code": "DE",
                    "frontier_cards_seen": cards_seen,
                    "frontier_cards_parsed": cards_parsed,
                },
            ) from exc

        return SourceBatch(
            items=list(items_by_id.values()),
            next_cursor={
                "country_code": "DE",
                "newest_ids": list(items_by_id)[:100],
                "frontier_cards_seen": cards_seen,
                "frontier_cards_parsed": cards_parsed,
                "frontier_unavailable_cards": unavailable_cards,
                "frontier_price_unknown_cards": price_unknown_cards,
                "frontier_out_of_budget_cards": out_of_budget_cards,
            },
            source_reported_count=source_reported_count,
            coverage_complete=False,
            result_cap_hit=bool(
                source_reported_count is not None
                and source_reported_count > len(items_by_id)
            ),
            pages_fetched=pages_fetched,
        )
