from __future__ import annotations

import asyncio
import math
import random
from typing import Any
from urllib.parse import urlparse

import httpx

from app.sources.base import PropertySource, RawProperty, SourceBatch, SourceShardSpec
from app.sources.property.immmo import (
    BUNDESLAENDER,
    COUNT_RE,
    IGNORED_EXTERNAL_HOSTS,
    LOCATION_AREA_RE,
    PAGE_SIZE,
    PLOT_PATTERNS,
    PRICE_RE,
    SEARCH_ROOT,
    _canonical_external_url,
    _clean_text,
    _decimal,
    _DOMParser,
    _Node,
    _source_id,
)


def _plot_area(text: str):
    for pattern in PLOT_PATTERNS:
        match = pattern.search(text)
        if match:
            return _decimal(match.group(1))
    return None


def _is_title_text(text: str) -> bool:
    cleaned = _clean_text(text)
    if len(cleaned) < 8 or len(cleaned) > 500:
        return False
    if cleaned.startswith(("#", "€")):
        return False
    if cleaned.casefold() in {"mehr", "weiter", "details"}:
        return False
    hostish = cleaned.casefold().removeprefix("www.")
    return not any(hostish == host.removeprefix("www.") for host in IGNORED_EXTERNAL_HOSTS)


def _card_for_external_anchor(anchor: _Node) -> tuple[_Node, Any] | None:
    """Find the smallest ancestor containing exactly one IMMMO facts row.

    The live IMMMO layout nests the original-link anchor separately from the
    PLZ/area facts row, so stopping at an arbitrary short parent loses metadata.
    A single facts row is a more stable card boundary than CSS classes or heading tags.
    """
    node = anchor.parent
    fallback: tuple[_Node, Any] | None = None
    for _ in range(16):
        if node is None or node.tag == "document":
            break
        text = node.text()
        matches = list(LOCATION_AREA_RE.finditer(text))
        if len(matches) == 1:
            fallback = (node, matches[0])
            if PRICE_RE.search(text):
                return fallback
        elif len(matches) > 1:
            break
        node = node.parent
    return fallback


def _best_title(card: _Node, *, page_url: str, original_url: str) -> str:
    candidates: list[str] = []
    for node in card.walk():
        if node.tag != "a":
            continue
        href = node.attrs.get("href")
        if not href:
            continue
        url = _canonical_external_url(href, page_url=page_url)
        if url != original_url:
            continue
        text = _clean_text(node.text())
        if _is_title_text(text):
            candidates.append(text)
    if candidates:
        return max(candidates, key=len)[:500]

    text = card.text()
    price = PRICE_RE.search(text)
    if price:
        prefix = text[: price.start()].strip()
        if len(prefix) >= 8:
            return prefix[-500:]
    return "Haus zum Kauf"


class ImmmoPage:
    __slots__ = ("count_is_lower_bound", "items", "reported_count")

    def __init__(self, items: list[RawProperty], reported_count: int | None, count_is_lower_bound: bool):
        self.items = items
        self.reported_count = reported_count
        self.count_is_lower_bound = count_is_lower_bound


def parse_immmo_search_page(html: str, *, page_url: str) -> ImmmoPage:
    parser = _DOMParser()
    parser.feed(html)
    page_text = parser.root.text()

    count_match = COUNT_RE.search(page_text)
    reported_count = None
    count_is_lower_bound = False
    if count_match:
        reported_count = int(count_match.group("count").replace(".", ""))
        count_is_lower_bound = bool(count_match.group("lower"))

    items_by_url: dict[str, RawProperty] = {}
    for anchor in parser.root.walk():
        if anchor.tag != "a":
            continue
        href = anchor.attrs.get("href")
        if not href:
            continue
        original_url = _canonical_external_url(href, page_url=page_url)
        if not original_url:
            continue

        card_info = _card_for_external_anchor(anchor)
        if card_info is None:
            continue
        card, facts = card_info
        text = card.text()

        postal_code = facts.group("plz")
        city = _clean_text(facts.group("city")).strip(" ,")
        living_area = _decimal(facts.group("area"))
        price_match = PRICE_RE.search(text)
        host = (urlparse(original_url).hostname or "").casefold()

        items_by_url[original_url] = RawProperty(
            source_listing_id=_source_id(original_url),
            url=original_url,
            title=_best_title(card, page_url=page_url, original_url=original_url),
            description=None,
            price_eur=_decimal(price_match.group(1)) if price_match else None,
            living_area_m2=living_area,
            plot_area_m2=_plot_area(text),
            postal_code=postal_code,
            city=city,
            raw_payload={
                "format": "immmo-search-discovery-v2",
                "original_host": host,
                "discovery_url": page_url,
            },
        )

    return ImmmoPage(list(items_by_url.values()), reported_count, count_is_lower_bound)


def _validate_page_quality(page: ImmmoPage, *, shard_key: str, page_number: int) -> None:
    if page.reported_count is not None and page.reported_count > 0 and not page.items:
        raise RuntimeError(
            f"IMMMO returned zero parseable listings for shard {shard_key!r} page {page_number}"
        )
    if len(page.items) < 6:
        return

    with_plz = sum(item.postal_code is not None for item in page.items)
    with_area = sum(item.living_area_m2 is not None for item in page.items)
    if with_plz / len(page.items) < 0.80 or with_area / len(page.items) < 0.60:
        raise RuntimeError(
            f"IMMMO metadata quality too low for shard {shard_key!r} page {page_number}: "
            f"PLZ {with_plz}/{len(page.items)}, living_area {with_area}/{len(page.items)}"
        )


class ImmmoPropertySource(PropertySource):
    """Low-rate IMMMO meta-search discovery adapter for Austrian houses for sale."""

    def __init__(
        self,
        *,
        request_delay_seconds: float = 0.45,
        incremental_pages: int = 2,
        hard_max_pages_per_shard: int = 500,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.name = "immmo.at"
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.incremental_pages = max(1, incremental_pages)
        self.hard_max_pages_per_shard = max(10, hard_max_pages_per_shard)
        self.timeout_seconds = timeout_seconds

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=key,
                params={"bundesland": slug, "search_url": f"{SEARCH_ROOT}/{slug}"},
                result_cap=self.hard_max_pages_per_shard * PAGE_SIZE,
            )
            for key, slug in BUNDESLAENDER
        ]

    async def _sleep(self) -> None:
        if self.request_delay_seconds:
            await asyncio.sleep(self.request_delay_seconds * random.uniform(0.8, 1.25))

    async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await client.get(url)
                if response.status_code in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                response.raise_for_status()
                if (response.url.host or "").casefold() not in {"immmo.at", "www.immmo.at"}:
                    raise RuntimeError(
                        f"IMMMO redirected off-site: requested={url!r} final={str(response.url)!r}"
                    )
                return response
            except (httpx.HTTPError, RuntimeError) as exc:
                last_error = exc
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)
        raise RuntimeError("unreachable") from last_error

    @staticmethod
    def _page_url(base_url: str, page: int) -> str:
        return base_url if page == 1 else f"{base_url}/{page}"

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        del cursor
        base_url = str(shard.params.get("search_url") or "")
        if not base_url.startswith(f"{SEARCH_ROOT}/"):
            raise ValueError(f"Invalid IMMMO shard URL: {base_url!r}")

        headers = {
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian property search)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
        }
        items_by_id: dict[str, RawProperty] = {}
        reported_count: int | None = None
        count_is_lower_bound = False
        pages_fetched = 0
        result_cap_hit = False

        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            first = await self._get(client, self._page_url(base_url, 1))
            parsed = parse_immmo_search_page(first.text, page_url=str(first.url))
            if parsed.reported_count is None:
                raise RuntimeError(f"IMMMO result count missing for shard {shard.key!r}")
            _validate_page_quality(parsed, shard_key=shard.key, page_number=1)

            reported_count = parsed.reported_count
            count_is_lower_bound = parsed.count_is_lower_bound
            items_by_id.update({item.source_listing_id: item for item in parsed.items})
            pages_fetched = 1

            total_pages = max(1, math.ceil(reported_count / PAGE_SIZE))
            if reconciliation:
                result_cap_hit = count_is_lower_bound or total_pages > self.hard_max_pages_per_shard
                target_pages = min(total_pages, self.hard_max_pages_per_shard)
            else:
                target_pages = min(total_pages, self.incremental_pages)

            for page_number in range(2, target_pages + 1):
                await self._sleep()
                response = await self._get(client, self._page_url(base_url, page_number))
                page_data = parse_immmo_search_page(response.text, page_url=str(response.url))
                _validate_page_quality(page_data, shard_key=shard.key, page_number=page_number)
                items_by_id.update({item.source_listing_id: item for item in page_data.items})
                pages_fetched += 1

        count_plausible = len(items_by_id) >= max(1, int((reported_count or 0) * 0.90))
        coverage_complete = (
            reconciliation
            and not result_cap_hit
            and pages_fetched >= max(1, math.ceil((reported_count or 0) / PAGE_SIZE))
            and count_plausible
        )

        return SourceBatch(
            items=list(items_by_id.values()),
            next_cursor={"newest_ids": list(items_by_id)[:100]},
            source_reported_count=reported_count,
            coverage_complete=coverage_complete,
            result_cap_hit=result_cap_hit,
            pages_fetched=pages_fetched,
        )
