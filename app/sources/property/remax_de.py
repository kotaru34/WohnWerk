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
    GERMAN_REGIONS,
    GERMANY_PROPERTY_MAX_PRICE_EUR,
    GERMANY_PROPERTY_MIN_PRICE_EUR,
    REGIONS_BY_KEY,
)
from app.sources.property.immmo import _clean_text, _decimal, _DOMParser, _Node
from app.sources.property.preview import card_thumbnail_url

BASE_URL = "https://www.remax.de"
SEARCH_ROOT = f"{BASE_URL}/de/l/ol"
DEFAULT_HARD_MAX_CARDS = 80

_ALLOWED_HOSTS = {"remax.de", "www.remax.de"}
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_DETAIL_PATH_RE = re.compile(r"^/de/(?P<slug>[a-z0-9][a-z0-9-]{2,})/?$", re.IGNORECASE)
_LOCATION_ID_RE = re.compile(
    r"\bLage:\s*(?P<plz>\d{5})\s+(?P<city>.+?)\s+Haus:\s*(?P<listing_id>[A-Z0-9-]+)\b",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(
    r"\bEUR\s*(?P<price>[\d.]+(?:,\d{1,2})?)\s*Kaufpreis\b",
    re.IGNORECASE,
)
_LIVING_RE = re.compile(
    r"(?P<area>[\d.,]+)\s*m(?:²|2)\s*Wohnfläche\b",
    re.IGNORECASE,
)
_COUNT_RE = re.compile(
    r"(?P<count>[\d.]+)\s+Häuser(?:\s+in\s+.+?)?\s+zu\s+kaufen\s+und\s+zu\s+mieten",
    re.IGNORECASE,
)
_RENT_RE = re.compile(r"\b(?:Kaltmiete|Warmmiete|Monatsmiete)\b", re.IGNORECASE)
_UNAVAILABLE_RE = re.compile(r"\b(?:verkauft|reserviert)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RemaxPage:
    items: list[RawProperty]
    source_reported_count: int | None
    cards_seen: int
    cards_parsed: int
    rental_cards: int
    unavailable_cards: int
    price_unknown_cards: int
    out_of_budget_cards: int


def _canonical_detail_url(value: str, *, page_url: str) -> str | None:
    absolute = urljoin(page_url, value)
    parsed = urlparse(absolute)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or host not in _ALLOWED_HOSTS:
        return None
    match = _DETAIL_PATH_RE.match(parsed.path)
    if match is None:
        return None
    slug = match.group("slug").casefold()
    if slug in {"login", "kontakt", "karriere", "datenschutz", "impressum"}:
        return None
    return urlunparse(("https", "www.remax.de", parsed.path.rstrip("/"), "", "", ""))


def _detail_anchors(node: _Node, *, page_url: str) -> list[tuple[_Node, str]]:
    result: list[tuple[_Node, str]] = []
    seen: set[tuple[str, str]] = set()
    for child in node.walk():
        if child.tag != "a":
            continue
        url = _canonical_detail_url(child.attrs.get("href", ""), page_url=page_url)
        if url is None:
            continue
        key = (url, _clean_text(child.text()))
        if key in seen:
            continue
        seen.add(key)
        result.append((child, url))
    return result


def _card_for_anchor(anchor: _Node) -> _Node | None:
    node = anchor.parent
    fallback: _Node | None = None
    for _ in range(16):
        if node is None or node.tag == "document":
            break
        text = node.text()
        if _LOCATION_ID_RE.search(text) and (
            _PRICE_RE.search(text) or _RENT_RE.search(text)
        ):
            fallback = node
            if _LIVING_RE.search(text):
                return node
        node = node.parent
    return fallback


def _title_for_card(card: _Node, *, page_url: str, detail_url: str) -> str:
    values = [
        _clean_text(anchor.text())
        for anchor, url in _detail_anchors(card, page_url=page_url)
        if url == detail_url and 6 <= len(_clean_text(anchor.text())) <= 500
    ]
    return max(values, key=len, default="")


def parse_remax_search_page(html: str, *, page_url: str) -> RemaxPage:
    parser = _DOMParser()
    parser.feed(html)
    page_text = parser.root.text()

    count_match = _COUNT_RE.search(page_text)
    source_reported_count = (
        int(count_match.group("count").replace(".", "")) if count_match else None
    )

    candidates: list[tuple[_Node, str]] = []
    seen_urls: set[str] = set()
    for anchor, url in _detail_anchors(parser.root, page_url=page_url):
        card = _card_for_anchor(anchor)
        if card is None or url in seen_urls:
            continue
        seen_urls.add(url)
        candidates.append((card, url))

    items_by_id: dict[str, RawProperty] = {}
    cards_parsed = rental_cards = unavailable_cards = 0
    price_unknown_cards = out_of_budget_cards = 0

    for card, url in candidates:
        text = card.text()
        location = _LOCATION_ID_RE.search(text)
        if location is None:
            continue
        title = _title_for_card(card, page_url=page_url, detail_url=url)
        if not title:
            continue
        cards_parsed += 1

        if _RENT_RE.search(text) and _PRICE_RE.search(text) is None:
            rental_cards += 1
            continue
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
        listing_id = location.group("listing_id").upper()
        thumbnail_url = card_thumbnail_url(card, page_url=page_url)
        city = _clean_text(location.group("city")).strip(" ,-")[:100]

        items_by_id[listing_id] = RawProperty(
            source_listing_id=listing_id,
            url=url,
            title=title[:500],
            price_eur=price,
            living_area_m2=(
                _decimal(living_match.group("area")) if living_match else None
            ),
            postal_code=location.group("plz"),
            city=city or None,
            raw_payload={
                "format": "remax-de-public-frontier-v1",
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

    return RemaxPage(
        items=list(items_by_id.values()),
        source_reported_count=source_reported_count,
        cards_seen=len(candidates),
        cards_parsed=cards_parsed,
        rental_cards=rental_cards,
        unavailable_cards=unavailable_cards,
        price_unknown_cards=price_unknown_cards,
        out_of_budget_cards=out_of_budget_cards,
    )


def _validate_page(page: RemaxPage, *, shard_key: str) -> None:
    if page.source_reported_count and page.cards_seen == 0:
        raise RuntimeError(f"RE/MAX returned no identifiable cards for non-empty shard {shard_key}")
    if page.cards_seen != page.cards_parsed:
        raise RuntimeError(
            f"RE/MAX card parsing incomplete for {shard_key}: "
            f"parsed {page.cards_parsed}/{page.cards_seen}"
        )


class RemaxGermanyPropertySource(PropertySource):
    """Bounded public RE/MAX Germany state frontiers."""

    name = "remax-de"

    def __init__(
        self,
        *,
        request_delay_seconds: float = 3.0,
        timeout_seconds: float = 30.0,
        hard_max_cards: int = DEFAULT_HARD_MAX_CARDS,
    ) -> None:
        self.request_delay_seconds = max(2.0, request_delay_seconds)
        self.timeout_seconds = timeout_seconds
        self.hard_max_cards = max(1, hard_max_cards)
        self._requests_made = 0

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=region.key,
                params={"country_code": "DE", "region": region.key},
                result_cap=self.hard_max_cards,
                priority=70,
            )
            for region in GERMAN_REGIONS
        ]

    @staticmethod
    def _shard_url(shard: SourceShardSpec) -> str:
        region = REGIONS_BY_KEY[str(shard.params["region"])]
        return f"{SEARCH_ROOT}/haeuser-{region.immoscout_slug}"

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
                    raise RuntimeError(f"RE/MAX redirected off-site: {response.url!s}")
                if response.status_code in {401, 403}:
                    raise SourceFetchError(
                        f"RE/MAX access gate HTTP {response.status_code}",
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
        del cursor, reconciliation
        url = self._shard_url(shard)
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
                response = await self._get(client, url)
                page = parse_remax_search_page(response.text, page_url=str(response.url))
                _validate_page(page, shard_key=shard.key)
        except SourceFetchError:
            raise
        except Exception as exc:
            raise SourceFetchError(
                f"RE/MAX frontier failed for {shard.key}: {type(exc).__name__}: {exc}",
                pages_fetched=0,
                next_cursor={"country_code": "DE", "region": shard.key},
            ) from exc

        return SourceBatch(
            items=page.items,
            next_cursor={
                "country_code": "DE",
                "region": shard.key,
                "frontier_cards_seen": page.cards_seen,
                "frontier_cards_parsed": page.cards_parsed,
                "frontier_rental_cards": page.rental_cards,
                "frontier_unavailable_cards": page.unavailable_cards,
                "frontier_price_unknown_cards": page.price_unknown_cards,
                "frontier_out_of_budget_cards": page.out_of_budget_cards,
            },
            source_reported_count=page.source_reported_count,
            coverage_complete=False,
            result_cap_hit=bool(
                page.source_reported_count is not None
                and page.source_reported_count > page.cards_seen
            ),
            pages_fetched=1,
        )
