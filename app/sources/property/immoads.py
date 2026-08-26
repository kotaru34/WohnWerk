from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import httpx

from app.sources.base import PropertySource, RawProperty, SourceBatch, SourceShardSpec

BASE_URL = "https://www.immoads.at"
SEARCH_URL = f"{BASE_URL}/immobilien/haus-kaufen"
DETAIL_PATH_RE = re.compile(
    r"^/immobilien/haus-kaufen/(?:[^/?#]+/)+(?P<listing_id>\d{6,10})-[^/?#]+/?$",
    re.IGNORECASE,
)
COUNT_RE = re.compile(r"Es wurden\s+([\d.]+)\s+Objekte gefunden", re.IGNORECASE)
AREA_RE = re.compile(r"([\d.]+(?:,\d+)?)\s*m(?:²|2)\b", re.IGNORECASE)
PRICE_RE = re.compile(r"€?\s*([\d.]+(?:,\d{1,2})?)")

_BLOCK_TAGS = {
    "address",
    "article",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "header",
    "li",
    "main",
    "p",
    "section",
    "table",
    "td",
    "th",
    "tr",
}


class _VisibleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self._current_anchor: str | None = None
        self._anchor_text: list[str] = []
        self._current_heading: str | None = None
        self._heading_text: list[str] = []
        self.text_parts: list[str] = []
        self.anchors: list[tuple[str, str]] = []
        self.headings: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1
            return
        if self._hidden_depth:
            return
        if tag in _BLOCK_TAGS:
            self.text_parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href")
            self._current_anchor = href
            self._anchor_text = []
        if tag in {"h1", "h2", "h3"}:
            self._current_heading = tag
            self._heading_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)
            return
        if self._hidden_depth:
            return
        if tag == "a" and self._current_anchor is not None:
            text = _clean_inline(" ".join(self._anchor_text))
            self.anchors.append((self._current_anchor, text))
            self._current_anchor = None
            self._anchor_text = []
        if tag == self._current_heading:
            text = _clean_inline(" ".join(self._heading_text))
            if text:
                self.headings.append((tag, text))
            self._current_heading = None
            self._heading_text = []
        if tag in _BLOCK_TAGS:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        self.text_parts.append(data)
        if self._current_anchor is not None:
            self._anchor_text.append(data)
        if self._current_heading is not None:
            self._heading_text.append(data)

    @property
    def lines(self) -> list[str]:
        return [
            line
            for line in (_clean_inline(part) for part in "".join(self.text_parts).splitlines())
            if line
        ]


def _clean_inline(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_page(html: str) -> _VisibleHTMLParser:
    parser = _VisibleHTMLParser()
    parser.feed(html)
    return parser


def _number(value: str) -> Decimal | None:
    match = re.search(r"[\d.]+(?:,\d+)?", value)
    if not match:
        return None
    raw = match.group(0)
    if "," in raw:
        normalized = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") > 1:
        normalized = raw.replace(".", "")
    elif raw.count(".") == 1 and len(raw.rsplit(".", 1)[1]) == 3:
        normalized = raw.replace(".", "")
    else:
        normalized = raw
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _area(value: str) -> Decimal | None:
    match = AREA_RE.search(value)
    return _number(match.group(1)) if match else _number(value)


def _price(value: str) -> Decimal | None:
    match = PRICE_RE.search(value)
    return _number(match.group(1)) if match else None


def _value_after(lines: list[str], labels: set[str]) -> str | None:
    folded_labels = {label.casefold() for label in labels}
    for index, line in enumerate(lines[:-1]):
        if line.casefold() in folded_labels:
            return lines[index + 1]
    return None


def _section(lines: list[str], start_label: str, stop_labels: set[str]) -> str | None:
    start = None
    for index, line in enumerate(lines):
        if line.casefold() == start_label.casefold():
            start = index + 1
            break
    if start is None:
        return None

    stop_folded = {label.casefold() for label in stop_labels}
    collected: list[str] = []
    for line in lines[start:]:
        if line.casefold() in stop_folded or line.casefold().startswith("objekt-nr."):
            break
        collected.append(line)
    text = "\n".join(collected).strip()
    return text[:30000] or None


def _plot_area_from_description(description: str | None) -> Decimal | None:
    if not description:
        return None
    patterns = [
        r"(?:rund|ca\.?)?\s*([\d.]+(?:,\d+)?)\s*m(?:²|2)\s+Grundstücksfläche",
        r"(?:rund|ca\.?)?\s*([\d.]+(?:,\d+)?)\s*m(?:²|2)\s+Grundstück\b",
        r"Grundstücksfläche\s*:?\s*(?:ca\.?\s*)?([\d.]+(?:,\d+)?)\s*m(?:²|2)",
        r"Grundstück\s+(?:mit\s+)?(?:ca\.?\s*)?([\d.]+(?:,\d+)?)\s*m(?:²|2)",
        r"(?:Gesamtfläche|Grundfläche)\s*(?:von|:)?\s*(?:ca\.?\s*)?([\d.]+(?:,\d+)?)\s*m(?:²|2)",
    ]
    for pattern in patterns:
        match = re.search(pattern, description, flags=re.IGNORECASE)
        if match:
            return _number(match.group(1))
    return None


def _normalize_listing_id(raw: str) -> str:
    return raw.lstrip("0") or "0"


@dataclass(frozen=True, slots=True)
class ImmoAdsListingRef:
    source_listing_id: str
    url: str
    title_hint: str | None = None


def parse_immoads_search_page(
    html: str,
    *,
    page_url: str,
) -> tuple[list[ImmoAdsListingRef], int | None, int | None]:
    parser = _parse_page(html)
    refs: dict[str, ImmoAdsListingRef] = {}
    max_page: int | None = None

    for href, anchor_text in parser.anchors:
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        match = DETAIL_PATH_RE.match(parsed.path.rstrip("/"))
        if match:
            listing_id = _normalize_listing_id(match.group("listing_id"))
            title_hint = anchor_text if len(anchor_text) >= 4 else None
            refs.setdefault(
                listing_id,
                ImmoAdsListingRef(
                    source_listing_id=listing_id,
                    url=urlunparse(("https", "www.immoads.at", parsed.path, "", "", "")),
                    title_hint=title_hint,
                ),
            )

        query = parse_qs(parsed.query)
        for raw_page in query.get("page", []):
            if raw_page.isdigit():
                page = int(raw_page)
                if 1 <= page <= 10000:
                    max_page = max(max_page or 0, page)

    text = "\n".join(parser.lines)
    count_match = COUNT_RE.search(text)
    reported_count = int(count_match.group(1).replace(".", "")) if count_match else None
    return list(refs.values()), reported_count, max_page


def parse_immoads_detail(
    html: str,
    *,
    url: str,
    source_listing_id: str,
) -> RawProperty | None:
    parser = _parse_page(html)
    lines = parser.lines
    if not lines:
        return None

    lowered = "\n".join(lines).casefold()
    if "seite existiert nicht mehr" in lowered:
        return None

    title = next((text for tag, text in parser.headings if tag == "h1"), None)
    if not title:
        title = f"Haus {source_listing_id}"
    if title.casefold().startswith(("verkauft", "vermietet")):
        return None

    postal_code = _value_after(lines, {"PLZ"})
    if postal_code:
        postal_match = re.search(r"\b(\d{4})\b", postal_code)
        postal_code = postal_match.group(1) if postal_match else None
    city = _value_after(lines, {"Ort"})

    price_text = _value_after(lines, {"Kaufpreis", "Kaufpreis brutto"})
    overview_area_text = _value_after(lines, {"Fläche"})
    living_area_text = _value_after(lines, {"Wohnfläche m²", "Wohnfläche"})
    plot_area_text = _value_after(lines, {"Grundstücksfläche m²", "Grundstücksfläche"})

    description = _section(
        lines,
        "Beschreibung & Informationen",
        {
            "Anbieter:",
            "Lage",
            "Kosten",
            "Merkmale",
            "Ausstattung",
            "Energie",
            "Anbieter kontaktieren",
        },
    )
    plot_area = _area(plot_area_text) if plot_area_text else _plot_area_from_description(description)

    return RawProperty(
        source_listing_id=source_listing_id,
        url=url,
        title=title,
        description=description,
        price_eur=_price(price_text) if price_text else None,
        living_area_m2=_area(living_area_text or overview_area_text or ""),
        plot_area_m2=plot_area,
        postal_code=postal_code,
        city=city,
        raw_payload={
            "format": "immoads-html",
            "price_text": price_text,
            "overview_area_text": overview_area_text,
            "living_area_text": living_area_text,
            "plot_area_text": plot_area_text,
        },
    )


class ImmoAdsPropertySource(PropertySource):
    """Coverage-aware public-search adapter for Austrian houses for sale on ImmoAds."""

    def __init__(
        self,
        *,
        request_delay_seconds: float = 0.65,
        incremental_pages: int = 5,
        hard_max_pages: int = 200,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.name = "immoads.at"
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.incremental_pages = max(1, incremental_pages)
        self.hard_max_pages = max(10, hard_max_pages)
        self.timeout_seconds = timeout_seconds

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key="at-house-buy",
                params={"search_url": SEARCH_URL},
                result_cap=self.hard_max_pages * 10,
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
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)
        raise RuntimeError("unreachable") from last_error

    @staticmethod
    def _page_url(page: int) -> str:
        query = urlencode({"order": "latest", "page": page})
        return f"{SEARCH_URL}?{query}"

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        del cursor
        if shard.key != "at-house-buy":
            raise ValueError(f"Unknown ImmoAds shard: {shard.key}")

        headers = {
            "User-Agent": "WohnWerk/0.1 (+self-hosted personal property search; low-rate crawler)",
            "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
        }
        refs: dict[str, ImmoAdsListingRef] = {}
        reported_count: int | None = None
        detected_max_page: int | None = None
        pages_fetched = 0
        listing_pages_complete = False
        result_cap_hit = False

        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            first_url = self._page_url(1)
            first = await self._get(client, first_url)
            first.raise_for_status()
            first_refs, reported_count, detected_max_page = parse_immoads_search_page(
                first.text,
                page_url=str(first.url),
            )
            refs.update({ref.source_listing_id: ref for ref in first_refs})
            pages_fetched = 1

            if detected_max_page is None:
                target_pages = 1 if not reconciliation else self.hard_max_pages
            elif reconciliation:
                target_pages = min(detected_max_page, self.hard_max_pages)
                result_cap_hit = detected_max_page > self.hard_max_pages
            else:
                target_pages = min(detected_max_page, self.incremental_pages)

            empty_tail = 0
            for page in range(2, target_pages + 1):
                await self._sleep()
                response = await self._get(client, self._page_url(page))
                response.raise_for_status()
                page_refs, page_count, page_max = parse_immoads_search_page(
                    response.text,
                    page_url=str(response.url),
                )
                pages_fetched += 1
                if reported_count is None and page_count is not None:
                    reported_count = page_count
                if page_max is not None:
                    detected_max_page = max(detected_max_page or 0, page_max)

                before = len(refs)
                refs.update({ref.source_listing_id: ref for ref in page_refs})
                empty_tail = empty_tail + 1 if len(refs) == before else 0
                if detected_max_page is None and reconciliation and empty_tail >= 2:
                    listing_pages_complete = True
                    break

            if reconciliation and detected_max_page is not None and not result_cap_hit:
                listing_pages_complete = pages_fetched >= detected_max_page
            elif not reconciliation:
                listing_pages_complete = False

            items: list[RawProperty] = []
            transient_detail_failures = 0
            for ref in refs.values():
                await self._sleep()
                try:
                    response = await self._get(client, ref.url)
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    item = parse_immoads_detail(
                        response.text,
                        url=str(response.url),
                        source_listing_id=ref.source_listing_id,
                    )
                    if item is not None:
                        items.append(item)
                except httpx.HTTPError:
                    transient_detail_failures += 1

        allowable_detail_failures = max(3, len(refs) // 100)
        details_reliable = transient_detail_failures <= allowable_detail_failures
        count_plausible = reported_count is None or len(refs) >= max(
            1,
            int(reported_count * 0.85),
        )
        coverage_complete = (
            reconciliation
            and listing_pages_complete
            and not result_cap_hit
            and details_reliable
            and count_plausible
            and bool(refs)
        )

        return SourceBatch(
            items=items,
            next_cursor={"first_page_ids": list(refs)[:100]},
            source_reported_count=reported_count,
            coverage_complete=coverage_complete,
            result_cap_hit=result_cap_hit,
            pages_fetched=pages_fetched,
        )
