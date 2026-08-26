from __future__ import annotations

import asyncio
import hashlib
import math
import random
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from app.sources.base import PropertySource, RawProperty, SourceBatch, SourceShardSpec

BASE_URL = "https://www.immmo.at"
SEARCH_ROOT = f"{BASE_URL}/immo/Haus-kaufen"
PAGE_SIZE = 12

BUNDESLAENDER: tuple[tuple[str, str], ...] = (
    ("burgenland", "Burgenland"),
    ("kaernten", "Kaernten"),
    ("niederoesterreich", "Niederoesterreich"),
    ("oberoesterreich", "Oberoesterreich"),
    ("salzburg", "Salzburg"),
    ("steiermark", "Steiermark"),
    ("tirol", "Tirol"),
    ("vorarlberg", "Vorarlberg"),
    ("wien", "Wien"),
)

COUNT_RE = re.compile(
    r"1\s+bis\s+12\s+von\s+(?P<lower>mehr\s+als\s+)?(?P<count>[\d.]+)",
    re.IGNORECASE,
)
PRICE_RE = re.compile(r"€\s*([\d.]+(?:,\d{1,2})?)")
LOCATION_AREA_RE = re.compile(
    r"\b(?P<plz>\d{4})\s+(?P<city>[^/\n]{1,120}?)\s*/\s*"
    r"(?P<area>[\d.]+(?:,\d+)?)\s*m(?:²|2)\b",
    re.IGNORECASE,
)
PLZ_CITY_RE = re.compile(r"\b(?P<plz>\d{4})\s+(?P<city>[^/\n]{1,120}?)(?:\s*/|$)")
PLOT_PATTERNS = (
    re.compile(
        r"Grundstücksfläche\s*(?:von|:)?\s*(?:ca\.?\s*)?([\d.]+(?:,\d+)?)\s*m(?:²|2)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:ca\.?\s*|rund\s+)?([\d.]+(?:,\d+)?)\s*m(?:²|2)\s+"
        r"(?:groß(?:en|es|e)?\s+)?Grundstück(?:sfläche)?\b",
        re.IGNORECASE,
    ),
)

IGNORED_EXTERNAL_HOSTS = {
    "www.googletagmanager.com",
    "googletagmanager.com",
    "www.google-analytics.com",
    "google-analytics.com",
    "www.facebook.com",
    "facebook.com",
    "www.instagram.com",
    "instagram.com",
}


@dataclass(slots=True)
class _Node:
    tag: str
    attrs: dict[str, str]
    parent: _Node | None = None
    text_parts: list[str] = field(default_factory=list)
    children: list[_Node] = field(default_factory=list)

    def text(self) -> str:
        parts: list[str] = []

        def collect(node: _Node) -> None:
            parts.extend(node.text_parts)
            for child in node.children:
                collect(child)

        collect(self)
        return _clean_text(" ".join(parts))

    def walk(self) -> Iterator[_Node]:
        yield self
        for child in self.children:
            yield from child.walk()


class _DOMParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self.stack = [self.root]
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        node = _Node(
            tag=tag,
            attrs={key.casefold(): value or "" for key, value in attrs},
            parent=self.stack[-1],
        )
        self.stack[-1].children.append(node)
        self.stack.append(node)
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        node = _Node(
            tag=tag,
            attrs={key.casefold(): value or "" for key, value in attrs},
            parent=self.stack[-1],
        )
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                popped = self.stack[index:]
                del self.stack[index:]
                if any(node.tag in {"script", "style", "noscript", "template"} for node in popped):
                    self.hidden_depth = max(0, self.hidden_depth - 1)
                return

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.stack[-1].text_parts.append(data)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    match = re.search(r"[\d.]+(?:,\d+)?", value)
    if not match:
        return None
    raw = match.group(0)
    dot_count = raw.count(".")
    if "," in raw:
        normalized = raw.replace(".", "").replace(",", ".")
    elif dot_count > 1 or (dot_count == 1 and len(raw.rsplit(".", 1)[1]) == 3):
        normalized = raw.replace(".", "")
    else:
        normalized = raw
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _canonical_external_url(raw_url: str, *, page_url: str) -> str | None:
    absolute = urljoin(page_url, raw_url)
    parsed = urlparse(absolute)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or not host:
        return None
    if host in {"immmo.at", "www.immmo.at"} or host in IGNORED_EXTERNAL_HOSTS:
        return None
    return urlunparse((parsed.scheme, parsed.netloc.casefold(), parsed.path, "", parsed.query, ""))


def _property_container(anchor: _Node) -> _Node | None:
    node = anchor.parent
    fallback: _Node | None = None
    for _ in range(10):
        if node is None or node.tag == "document":
            break
        text = node.text()
        has_location = re.search(r"\b\d{4}\b", text) is not None
        has_property_signal = "€" in text or re.search(r"\bm(?:²|2)\b", text, re.IGNORECASE)
        if has_location and has_property_signal:
            fallback = node
            if node.tag in {"article", "li", "section"}:
                return node
            if len(text) >= 80:
                return node
        node = node.parent
    return fallback


def _title_from_anchor(anchor: _Node, container_text: str) -> str:
    anchor_text = anchor.text()
    if (
        len(anchor_text) >= 8
        and "€" not in anchor_text
        and not anchor_text.startswith("#")
        and not re.fullmatch(r"(?:https?://)?[\w.-]+/?", anchor_text)
    ):
        return anchor_text[:500]

    match = re.search(r"Haus kaufen in \d{4}[^€]{0,160}?\s+(.{8,250}?)\s+€", container_text)
    if match:
        return _clean_text(match.group(1))[:500]
    return "Haus zum Kauf"


def _plot_area(text: str) -> Decimal | None:
    for pattern in PLOT_PATTERNS:
        match = pattern.search(text)
        if match:
            return _decimal(match.group(1))
    return None


def _source_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class ImmmoPage:
    items: list[RawProperty]
    reported_count: int | None
    count_is_lower_bound: bool


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

    by_url: dict[str, tuple[_Node, _Node]] = {}
    for node in parser.root.walk():
        if node.tag != "a":
            continue
        href = node.attrs.get("href")
        if not href:
            continue
        original_url = _canonical_external_url(href, page_url=page_url)
        if not original_url:
            continue
        container = _property_container(node)
        if container is None:
            continue
        text = container.text()
        if not re.search(r"\b\d{4}\b", text):
            continue
        existing = by_url.get(original_url)
        if existing is None or len(node.text()) > len(existing[0].text()):
            by_url[original_url] = (node, container)

    items: list[RawProperty] = []
    for original_url, (anchor, container) in by_url.items():
        text = container.text()
        location_match = LOCATION_AREA_RE.search(text)
        if location_match:
            postal_code = location_match.group("plz")
            city = _clean_text(location_match.group("city")).strip(" ,")
            living_area = _decimal(location_match.group("area"))
        else:
            plz_match = PLZ_CITY_RE.search(text)
            postal_code = plz_match.group("plz") if plz_match else None
            city = _clean_text(plz_match.group("city")).strip(" ,") if plz_match else None
            living_area = None

        price_match = PRICE_RE.search(text)
        host = (urlparse(original_url).hostname or "").casefold()
        items.append(
            RawProperty(
                source_listing_id=_source_id(original_url),
                url=original_url,
                title=_title_from_anchor(anchor, text),
                description=None,
                price_eur=_decimal(price_match.group(1)) if price_match else None,
                living_area_m2=living_area,
                plot_area_m2=_plot_area(text),
                postal_code=postal_code,
                city=city,
                raw_payload={
                    "format": "immmo-search-discovery",
                    "original_host": host,
                    "discovery_url": page_url,
                },
            )
        )

    return ImmmoPage(
        items=items,
        reported_count=reported_count,
        count_is_lower_bound=count_is_lower_bound,
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
                final_host = (response.url.host or "").casefold()
                if final_host not in {"immmo.at", "www.immmo.at"}:
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
            first_url = self._page_url(base_url, 1)
            first = await self._get(client, first_url)
            parsed = parse_immmo_search_page(first.text, page_url=str(first.url))
            if parsed.reported_count is None:
                raise RuntimeError(f"IMMMO result count missing for shard {shard.key!r}")
            if parsed.reported_count > 0 and not parsed.items:
                raise RuntimeError(f"IMMMO returned zero parseable listings for shard {shard.key!r}")

            reported_count = parsed.reported_count
            count_is_lower_bound = parsed.count_is_lower_bound
            items_by_id.update({item.source_listing_id: item for item in parsed.items})
            pages_fetched = 1

            total_pages = max(1, math.ceil(reported_count / PAGE_SIZE))
            if reconciliation:
                result_cap_hit = (
                    count_is_lower_bound or total_pages > self.hard_max_pages_per_shard
                )
                target_pages = min(total_pages, self.hard_max_pages_per_shard)
            else:
                target_pages = min(total_pages, self.incremental_pages)

            for page in range(2, target_pages + 1):
                await self._sleep()
                response = await self._get(client, self._page_url(base_url, page))
                page_data = parse_immmo_search_page(response.text, page_url=str(response.url))
                if not page_data.items and page <= total_pages:
                    raise RuntimeError(
                        f"IMMMO page {page} unexpectedly contained no parseable listings "
                        f"for shard {shard.key!r}"
                    )
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
