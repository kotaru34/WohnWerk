from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

import httpx

from app.sources.base import PropertySource, RawProperty, SourceBatch, SourceShardSpec
from app.sources.property.immmo import _clean_text, _decimal

BASE_URL = "https://www.sreal.at"
SEARCH_URL = f"{BASE_URL}/de/haeuser-kauf/angebot/10"
DETAIL_PATH_RE = re.compile(r"^/de/immobilie/(?P<listing_id>[^/]+)/", re.IGNORECASE)
AREA_RE = re.compile(
    r"(?:(?:ab|ca\.)\s+)?(?P<area>[\d.]+(?:,\d+)?)\s*m\s*(?:²|2)\s+"
    r"(?P<area_kind>Wohnfläche|Grundfläche|Nutzfläche)\b",
    re.IGNORECASE,
)
PRICE_RE = re.compile(
    r"(?:ab\s+)?(?P<price>[\d.]+(?:,\d+)?)\s*€\s*(?:Kaufpreis|Preis)\b",
    re.IGNORECASE,
)
PLZ_RE = re.compile(r"\b(?P<plz>\d{4})\s+")


@dataclass(frozen=True, slots=True)
class _Anchor:
    href: str
    text: str


@dataclass(slots=True)
class _AnchorFrame:
    href: str
    parts: list[str] = field(default_factory=list)


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[_Anchor] = []
        self._stack: list[_AnchorFrame] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1
            return
        if self._hidden_depth or tag != "a":
            return
        attributes = {key.casefold(): value or "" for key, value in attrs}
        href = attributes.get("href")
        if href:
            self._stack.append(_AnchorFrame(href=href))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)
            return
        if self._hidden_depth or tag != "a" or not self._stack:
            return
        frame = self._stack.pop()
        self.anchors.append(_Anchor(frame.href, _clean_text(" ".join(frame.parts))))

    def handle_data(self, data: str) -> None:
        if self._hidden_depth or not self._stack:
            return
        cleaned = _clean_text(data)
        if cleaned:
            self._stack[-1].parts.append(cleaned)


@dataclass(frozen=True, slots=True)
class _CardFacts:
    title: str
    postal_code: str
    city: str
    area: str
    area_kind: str
    price: str | None


@dataclass(frozen=True, slots=True)
class SRealPage:
    items: list[RawProperty]
    max_page: int
    cards_seen: int
    cards_parsed: int


def _canonical_detail_url(raw_url: str, *, page_url: str) -> tuple[str, str] | None:
    absolute = urljoin(page_url, raw_url)
    parsed = urlparse(absolute)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or host not in {"sreal.at", "www.sreal.at"}:
        return None
    match = DETAIL_PATH_RE.match(parsed.path)
    if match is None:
        return None
    canonical = urlunparse(("https", "www.sreal.at", parsed.path, "", "", ""))
    return canonical, match.group("listing_id")


def _max_page(anchors: list[_Anchor]) -> int:
    pages = [1]
    for anchor in anchors:
        parsed = urlparse(anchor.href)
        raw = parse_qs(parsed.query).get("p")
        if not raw:
            continue
        try:
            pages.append(int(raw[0]))
        except (TypeError, ValueError):
            continue
    return max(pages)


def _parse_card_facts(text: str) -> _CardFacts | None:
    area_match = AREA_RE.search(text)
    if area_match is None:
        return None

    prefix = _clean_text(text[: area_match.start()])
    plz_matches = list(PLZ_RE.finditer(prefix))
    if not plz_matches:
        return None
    location = plz_matches[-1]

    title = _clean_text(prefix[: location.start()]).rstrip(" -–") or "Haus zum Kauf"
    city = _clean_text(prefix[location.end() :]).strip(" ,")
    if not city:
        return None

    price_match = PRICE_RE.search(text[area_match.end() :])
    if price_match is None:
        price_match = PRICE_RE.search(text)

    return _CardFacts(
        title=title,
        postal_code=location.group("plz"),
        city=city,
        area=area_match.group("area"),
        area_kind=area_match.group("area_kind"),
        price=price_match.group("price") if price_match else None,
    )


def parse_sreal_search_page(html: str, *, page_url: str) -> SRealPage:
    parser = _AnchorParser()
    parser.feed(html)

    items_by_id: dict[str, RawProperty] = {}
    cards_seen = 0
    cards_parsed = 0

    for anchor in parser.anchors:
        detail = _canonical_detail_url(anchor.href, page_url=page_url)
        if detail is None:
            continue
        cards_seen += 1
        url, listing_id = detail
        facts = _parse_card_facts(anchor.text)
        if facts is None:
            continue

        cards_parsed += 1
        area = _decimal(facts.area)
        area_kind = facts.area_kind.casefold()
        price = _decimal(facts.price)

        items_by_id[listing_id] = RawProperty(
            source_listing_id=listing_id,
            url=url,
            title=facts.title[:500],
            description=None,
            price_eur=price,
            living_area_m2=area if area_kind == "wohnfläche" else None,
            plot_area_m2=area if area_kind == "grundfläche" else None,
            postal_code=facts.postal_code,
            city=facts.city,
            raw_payload={
                "format": "sreal-search-discovery-v2",
                "discovery_url": page_url,
                "source_postal_code": facts.postal_code,
                "listed_area_kind": facts.area_kind,
                "listed_area_m2": str(area) if area is not None else None,
                "identity_stable": True,
            },
        )

    return SRealPage(
        items=list(items_by_id.values()),
        max_page=_max_page(parser.anchors),
        cards_seen=cards_seen,
        cards_parsed=cards_parsed,
    )


def _validate_page(page: SRealPage, *, page_number: int, expected_minimum: int) -> None:
    if page.cards_seen == 0:
        raise RuntimeError(f"s REAL returned no property cards on page {page_number}")
    if page.cards_parsed < max(1, int(page.cards_seen * 0.90)):
        raise RuntimeError(
            f"s REAL metadata parsing incomplete on page {page_number}: "
            f"parsed {page.cards_parsed}/{page.cards_seen} cards"
        )
    if expected_minimum and page.cards_seen < expected_minimum:
        raise RuntimeError(
            f"s REAL page {page_number} unexpectedly short: "
            f"saw {page.cards_seen}, expected at least {expected_minimum}"
        )


class SRealPropertySource(PropertySource):
    """Low-rate direct s REAL house-for-sale discovery adapter."""

    def __init__(
        self,
        *,
        request_delay_seconds: float = 0.6,
        incremental_pages: int = 1,
        hard_max_pages: int = 100,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.name = "sreal.at"
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.incremental_pages = max(1, incremental_pages)
        self.hard_max_pages = max(5, hard_max_pages)
        self.timeout_seconds = timeout_seconds

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key="austria-houses-buy",
                params={"search_url": SEARCH_URL},
                result_cap=None,
            )
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
                if (response.url.host or "").casefold() not in {"sreal.at", "www.sreal.at"}:
                    raise RuntimeError(
                        f"s REAL redirected off-site: requested={url!r} final={str(response.url)!r}"
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
        return f"{base_url}?p={page}"

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        del cursor
        base_url = str(shard.params.get("search_url") or "")
        if base_url != SEARCH_URL:
            raise ValueError(f"Invalid s REAL shard URL: {base_url!r}")

        headers = {
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian property search)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
        }
        items_by_id: dict[str, RawProperty] = {}
        pages_fetched = 0
        cards_seen = 0
        cards_parsed = 0
        result_cap_hit = False

        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            first_response = await self._get(client, self._page_url(base_url, 1))
            first = parse_sreal_search_page(first_response.text, page_url=str(first_response.url))
            _validate_page(first, page_number=1, expected_minimum=0)

            page_size = first.cards_seen
            max_page = first.max_page
            if max_page > self.hard_max_pages:
                result_cap_hit = True
            target_pages = min(
                max_page,
                self.hard_max_pages,
                max_page if reconciliation else self.incremental_pages,
            )

            items_by_id.update({item.source_listing_id: item for item in first.items})
            pages_fetched = 1
            cards_seen = first.cards_seen
            cards_parsed = first.cards_parsed

            for page_number in range(2, target_pages + 1):
                await self._sleep()
                response = await self._get(client, self._page_url(base_url, page_number))
                page = parse_sreal_search_page(response.text, page_url=str(response.url))
                minimum = 0 if page_number == max_page else max(1, int(page_size * 0.75))
                _validate_page(page, page_number=page_number, expected_minimum=minimum)
                items_by_id.update({item.source_listing_id: item for item in page.items})
                pages_fetched += 1
                cards_seen += page.cards_seen
                cards_parsed += page.cards_parsed

        coverage_complete = (
            reconciliation
            and not result_cap_hit
            and pages_fetched == max_page
            and cards_seen == cards_parsed
        )

        return SourceBatch(
            items=list(items_by_id.values()),
            next_cursor={
                "newest_ids": list(items_by_id)[:100],
                "discovery_cards_seen": cards_seen,
                "discovery_cards_parsed": cards_parsed,
                "discovery_max_page": max_page,
            },
            source_reported_count=None,
            coverage_complete=coverage_complete,
            result_cap_hit=result_cap_hit,
            pages_fetched=pages_fetched,
        )
