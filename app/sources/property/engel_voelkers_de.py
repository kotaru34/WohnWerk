from __future__ import annotations

import asyncio
import json
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

BASE_URL = "https://www.engelvoelkers.com"
SEARCH_ROOT = f"{BASE_URL}/de/en/properties/res/sale/house"
DEFAULT_FRONTIER_PAGES = 8
DEFAULT_HARD_MAX_PAGES = 40

_EXPOSE_RE = re.compile(
    r"^/de/(?:en|de)/exposes/(?P<listing_id>[0-9a-f]{8}-[0-9a-f-]{27})/?$",
    re.IGNORECASE,
)
_COUNT_RE = re.compile(
    r"Houses\s+for\s+sale\s+in\s+Germany\s*[–-]\s*"
    r"(?P<count>[\d.,]+)\s+results",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(r"€\s*(?P<price>[\d.,]+)")
_PRICE_ON_REQUEST_RE = re.compile(r"(?:Price on request|Preis auf Anfrage)", re.IGNORECASE)
_LIVING_RE = re.compile(
    r"~?\s*(?P<area>[\d.,]+)\s*m(?:²|2)\s+Living\s+area",
    re.IGNORECASE,
)
_PLOT_RE = re.compile(
    r"~?\s*(?P<area>[\d.,]+)\s*m(?:²|2)\s+Plot\s+surface",
    re.IGNORECASE,
)
_UNAVAILABLE_RE = re.compile(
    r"^(?:VERKAUFT|SOLD|RESERVIERT|RESERVED)\b",
    re.IGNORECASE,
)
_ALLOWED_HOSTS = {"engelvoelkers.com", "www.engelvoelkers.com"}
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


@dataclass(frozen=True, slots=True)
class EngelVoelkersPage:
    items: list[RawProperty]
    source_reported_count: int
    cards_seen: int
    cards_parsed: int
    unavailable_cards: int
    price_unknown_cards: int
    out_of_budget_cards: int


def _english_decimal(value: str | None):
    """Parse E&V's English-locale numbers: comma thousands, dot decimals."""
    if not value:
        return None
    match = re.search(r"[\d,.]+", value)
    if match is None:
        return None
    raw = match.group(0).replace(",", "")
    return _decimal(raw)


def _canonical_expose_url(value: str, *, page_url: str) -> tuple[str, str] | None:
    absolute = urljoin(page_url, value)
    parsed = urlparse(absolute)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or host not in _ALLOWED_HOSTS:
        return None
    match = _EXPOSE_RE.match(parsed.path)
    if match is None:
        return None
    canonical = urlunparse(
        ("https", "www.engelvoelkers.com", parsed.path.rstrip("/"), "", "", "")
    )
    return canonical, match.group("listing_id").casefold()


def _structured_preview_urls(html: str, *, page_url: str) -> dict[str, str]:
    """Map expose IDs to source-backed preview URLs from E&V's public ItemList JSON-LD."""
    match = re.search(
        r"<script[^>]+id=['\"]structured-buyer-data-jsonld['\"][^>]*>(?P<body>.*?)</script>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return {}
    try:
        data = json.loads(match.group("body"))
    except json.JSONDecodeError:
        return {}

    items = data.get("itemListElement") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return {}

    previews: dict[str, str] = {}
    for entry in items:
        if not isinstance(entry, dict):
            continue
        detail = _canonical_expose_url(str(entry.get("url") or ""), page_url=page_url)
        image = str(entry.get("image") or "").strip()
        if detail is None or not image:
            continue
        parsed = urlparse(urljoin(page_url, image))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        previews[detail[1]] = parsed.geturl()
    return previews


def _expose_anchors(node: _Node, *, page_url: str) -> list[tuple[_Node, str, str]]:
    result: list[tuple[_Node, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for child in node.walk():
        if child.tag != "a":
            continue
        detail = _canonical_expose_url(child.attrs.get("href", ""), page_url=page_url)
        if detail is None:
            continue
        url, listing_id = detail
        key = (url, child.text())
        if key in seen:
            continue
        seen.add(key)
        result.append((child, url, listing_id))
    return result


def _card_for_anchor(anchor: _Node, *, page_url: str) -> _Node | None:
    node = anchor.parent
    fallback: _Node | None = None
    for _ in range(14):
        if node is None or node.tag == "document":
            break
        details = {item[2] for item in _expose_anchors(node, page_url=page_url)}
        if len(details) > 1:
            break

        text = node.text()
        has_location = ", Germany" in text
        has_price = (
            _PRICE_RE.search(text) is not None
            or _PRICE_ON_REQUEST_RE.search(text) is not None
        )
        has_area = _LIVING_RE.search(text) is not None or _PLOT_RE.search(text) is not None
        if len(details) == 1 and has_location and has_price:
            fallback = node
            if has_area:
                return node
        node = node.parent
    return fallback


def _direct_text_candidates(node: _Node) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for child in node.walk():
        value = _clean_text(" ".join(child.text_parts))
        if not value or len(value) > 240 or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _source_location(card: _Node) -> str | None:
    candidates = [
        value
        for value in _direct_text_candidates(card)
        if value.endswith(", Germany")
        and "€" not in value
        and "m²" not in value
        and len(value.split(",")) >= 2
    ]
    return min(candidates, key=len) if candidates else None


def _city_from_location(value: str | None) -> str | None:
    if not value:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if parts and parts[-1].casefold() == "germany":
        parts.pop()
    if not parts:
        return None
    # Engel & Völkers normally emits locality, municipality, Bundesland. Prefer the
    # municipality when present; for city states this intentionally remains locality.
    if len(parts) >= 3:
        return parts[-2][:100]
    return parts[0][:100]


def _title_anchor(card: _Node, *, page_url: str, listing_id: str) -> _Node | None:
    candidates = [
        anchor
        for anchor, _url, candidate_id in _expose_anchors(card, page_url=page_url)
        if candidate_id == listing_id and 8 <= len(anchor.text()) <= 500
    ]
    return max(candidates, key=lambda item: len(item.text()), default=None)


def parse_engel_voelkers_search_page(
    html: str,
    *,
    page_url: str,
) -> EngelVoelkersPage:
    parser = _DOMParser()
    parser.feed(html)
    page_text = parser.root.text()

    count_match = _COUNT_RE.search(page_text)
    if count_match is None:
        raise ValueError("Engel & Völkers Germany house result count is missing")
    source_reported_count = int(
        count_match.group("count").replace(".", "").replace(",", "")
    )

    items_by_id: dict[str, RawProperty] = {}
    structured_previews = _structured_preview_urls(html, page_url=page_url)
    title_exposes: dict[str, tuple[_Node, str]] = {}
    for anchor, url, listing_id in _expose_anchors(parser.root, page_url=page_url):
        title = _clean_text(anchor.text())
        if 8 <= len(title) <= 500:
            title_exposes.setdefault(listing_id, (anchor, url))

    cards_parsed = 0
    unavailable_cards = 0
    price_unknown_cards = 0
    out_of_budget_cards = 0

    for listing_id, (anchor, url) in title_exposes.items():
        card = _card_for_anchor(anchor, page_url=page_url)
        if card is None:
            continue

        title_node = _title_anchor(card, page_url=page_url, listing_id=listing_id)
        title = _clean_text(title_node.text()) if title_node is not None else ""
        location = _source_location(card)
        text = card.text()
        price_match = _PRICE_RE.search(text)
        price_on_request = _PRICE_ON_REQUEST_RE.search(text) is not None
        price = _english_decimal(price_match.group("price")) if price_match else None
        living_match = _LIVING_RE.search(text)
        plot_match = _PLOT_RE.search(text)
        thumbnail_url = structured_previews.get(listing_id)

        if not title or location is None or (price is None and not price_on_request):
            continue
        cards_parsed += 1

        if _UNAVAILABLE_RE.match(title):
            unavailable_cards += 1
            continue
        if price is None:
            price_unknown_cards += 1
            continue
        if (
            price < GERMANY_PROPERTY_MIN_PRICE_EUR
            or price > GERMANY_PROPERTY_MAX_PRICE_EUR
        ):
            out_of_budget_cards += 1
            continue

        items_by_id[listing_id] = RawProperty(
            source_listing_id=listing_id,
            url=url,
            title=title[:500],
            description=None,
            price_eur=price,
            living_area_m2=(
                _english_decimal(living_match.group("area")) if living_match else None
            ),
            plot_area_m2=(
                _english_decimal(plot_match.group("area")) if plot_match else None
            ),
            postal_code=None,
            city=_city_from_location(location),
            raw_payload={
                "format": "engel-voelkers-public-frontier-v1",
                "country_code": "DE",
                "discovery_url": page_url,
                "source_location": location,
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

    return EngelVoelkersPage(
        items=list(items_by_id.values()),
        source_reported_count=source_reported_count,
        cards_seen=len(title_exposes),
        cards_parsed=cards_parsed,
        unavailable_cards=unavailable_cards,
        price_unknown_cards=price_unknown_cards,
        out_of_budget_cards=out_of_budget_cards,
    )


def _validate_page(page: EngelVoelkersPage, *, page_number: int) -> None:
    if page.source_reported_count and page.cards_seen == 0:
        raise RuntimeError(
            "Engel & Völkers returned no identifiable expose cards "
            f"on non-empty page {page_number}"
        )
    if page.cards_seen != page.cards_parsed:
        raise RuntimeError(
            "Engel & Völkers card parsing incomplete on page "
            f"{page_number}: parsed {page.cards_parsed}/{page.cards_seen}"
        )


class EngelVoelkersGermanyPropertySource(PropertySource):
    """Bounded newest-first public Engel & Völkers Germany house frontier."""

    name = "engel-voelkers-de"

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
                key="de-newest-frontier",
                params={"country_code": "DE"},
                result_cap=self.hard_max_pages * 30,
                priority=60,
            )
        ]

    @staticmethod
    def _page_url(page: int) -> str:
        if page <= 1:
            return f"{SEARCH_ROOT}?sorting=publishedAt"
        return f"{SEARCH_ROOT}?page={page}&sorting=publishedAt"

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
                    raise RuntimeError(
                        f"Engel & Völkers redirected off-site: {response.url!s}"
                    )
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                if status in {401, 403}:
                    raise SourceFetchError(
                        f"Engel & Völkers access gate HTTP {status}",
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
        del shard, cursor, reconciliation
        items_by_id: dict[str, RawProperty] = {}
        pages_fetched = 0
        cards_seen = 0
        cards_parsed = 0
        unavailable_cards = 0
        price_unknown_cards = 0
        out_of_budget_cards = 0
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
                    page = parse_engel_voelkers_search_page(
                        response.text,
                        page_url=str(response.url),
                    )
                    _validate_page(page, page_number=page_number)
                    source_reported_count = max(
                        source_reported_count or 0,
                        page.source_reported_count,
                    )
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
                    "frontier_cards_seen": cards_seen,
                    "frontier_cards_parsed": cards_parsed,
                    "frontier_unavailable_cards": unavailable_cards,
                    "frontier_price_unknown_cards": price_unknown_cards,
                    "frontier_out_of_budget_cards": out_of_budget_cards,
                    "country_code": "DE",
                }
                raise
            raise SourceFetchError(
                f"Engel & Völkers frontier failed: {type(exc).__name__}: {exc}",
                pages_fetched=pages_fetched,
                items_seen=len(items_by_id),
                source_reported_count=source_reported_count,
                partial_items=list(items_by_id.values()),
                next_cursor={
                    "frontier_cards_seen": cards_seen,
                    "frontier_cards_parsed": cards_parsed,
                    "frontier_unavailable_cards": unavailable_cards,
                    "frontier_price_unknown_cards": price_unknown_cards,
                    "frontier_out_of_budget_cards": out_of_budget_cards,
                    "country_code": "DE",
                },
            ) from exc

        return SourceBatch(
            items=list(items_by_id.values()),
            next_cursor={
                "newest_ids": list(items_by_id)[:100],
                "frontier_cards_seen": cards_seen,
                "frontier_cards_parsed": cards_parsed,
                "frontier_unavailable_cards": unavailable_cards,
                "frontier_price_unknown_cards": price_unknown_cards,
                "frontier_out_of_budget_cards": out_of_budget_cards,
                "country_code": "DE",
            },
            source_reported_count=source_reported_count,
            coverage_complete=False,
            result_cap_hit=bool(
                source_reported_count is not None
                and source_reported_count > len(items_by_id)
            ),
            pages_fetched=pages_fetched,
        )
