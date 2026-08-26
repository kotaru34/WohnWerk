from __future__ import annotations

import asyncio
import math
import random
import re
from dataclasses import dataclass, field
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.sources.base import (
    PropertySource,
    RawProperty,
    SourceBatch,
    SourceFetchError,
    SourceShardSpec,
)
from app.sources.property.immmo import (
    BUNDESLAENDER,
    IGNORED_EXTERNAL_HOSTS,
    LOCATION_AREA_RE,
    PAGE_SIZE,
    PLOT_PATTERNS,
    PRICE_RE,
    SEARCH_ROOT,
    _canonical_external_url,
    _clean_text,
    _decimal,
    _source_id,
)

RESULT_HEADING_RE = re.compile(
    r"^(?P<kind>.+?)\s+kaufen\s+in\s+(?P<plz>\d{4})\s+(?P<city>.+?)$",
    re.IGNORECASE,
)
LIVE_COUNT_RE = re.compile(
    r"\d+\s+bis\s+\d+\s+von\s+(?P<lower>mehr\s+als\s+)?(?P<count>[\d.]+)",
    re.IGNORECASE,
)
HEADING_TAGS = {"h2", "h3", "h4", "h5"}


@dataclass(frozen=True, slots=True)
class _AnchorOccurrence:
    href: str
    text: str
    start: int
    end: int


@dataclass(slots=True)
class _AnchorFrame:
    href: str
    start: int
    parts: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _HeadingOccurrence:
    text: str
    start: int
    end: int


@dataclass(slots=True)
class _HeadingFrame:
    tag: str
    start: int
    parts: list[str] = field(default_factory=list)


class _VisibleStreamParser(HTMLParser):
    """Keep visible text order plus anchor/heading offsets without trusting card nesting."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._length = 0
        self._hidden_depth = 0
        self._anchors: list[_AnchorOccurrence] = []
        self._anchor_stack: list[_AnchorFrame] = []
        self._headings: list[_HeadingOccurrence] = []
        self._heading_stack: list[_HeadingFrame] = []

    @property
    def text(self) -> str:
        return "".join(self._chunks)

    @property
    def anchors(self) -> list[_AnchorOccurrence]:
        return self._anchors

    @property
    def headings(self) -> list[_HeadingOccurrence]:
        return self._headings

    def _append(self, value: str) -> None:
        cleaned = _clean_text(value)
        if not cleaned:
            return
        prefix = " " if self._length else ""
        self._chunks.append(prefix + cleaned)
        self._length += len(prefix) + len(cleaned)
        if self._anchor_stack:
            self._anchor_stack[-1].parts.append(cleaned)
        if self._heading_stack:
            self._heading_stack[-1].parts.append(cleaned)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1
            return
        if self._hidden_depth:
            return

        if tag in HEADING_TAGS:
            self._heading_stack.append(_HeadingFrame(tag=tag, start=self._length))

        if tag == "a":
            attributes = {key.casefold(): value or "" for key, value in attrs}
            href = attributes.get("href")
            if href:
                self._anchor_stack.append(_AnchorFrame(href=href, start=self._length))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)
            return
        if self._hidden_depth:
            return

        if tag == "a" and self._anchor_stack:
            frame = self._anchor_stack.pop()
            self._anchors.append(
                _AnchorOccurrence(
                    href=frame.href,
                    text=_clean_text(" ".join(frame.parts)),
                    start=frame.start,
                    end=self._length,
                )
            )

        if tag in HEADING_TAGS and self._heading_stack:
            for index in range(len(self._heading_stack) - 1, -1, -1):
                if self._heading_stack[index].tag != tag:
                    continue
                frame = self._heading_stack.pop(index)
                self._headings.append(
                    _HeadingOccurrence(
                        text=_clean_text(" ".join(frame.parts)),
                        start=frame.start,
                        end=self._length,
                    )
                )
                break

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self._append(data)


def _plot_area(text: str) -> Decimal | None:
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


class ImmmoPage:
    __slots__ = (
        "cards_parsed",
        "cards_seen",
        "count_is_lower_bound",
        "current_page",
        "has_next_page",
        "items",
        "pagination_max_page",
        "reported_count",
    )

    def __init__(
        self,
        items: list[RawProperty],
        reported_count: int | None,
        count_is_lower_bound: bool,
        cards_seen: int,
        cards_parsed: int,
        current_page: int,
        pagination_max_page: int,
        has_next_page: bool,
    ) -> None:
        self.items = items
        self.reported_count = reported_count
        self.count_is_lower_bound = count_is_lower_bound
        self.cards_seen = cards_seen
        self.cards_parsed = cards_parsed
        self.current_page = current_page
        self.pagination_max_page = pagination_max_page
        self.has_next_page = has_next_page


def _select_original_anchor(
    anchors: list[_AnchorOccurrence],
    *,
    segment_start: int,
    segment_end: int,
    page_url: str,
) -> tuple[_AnchorOccurrence, str] | None:
    fallback: tuple[_AnchorOccurrence, str] | None = None
    for anchor in anchors:
        if anchor.start < segment_start:
            continue
        if anchor.start >= segment_end:
            break
        original_url = _canonical_external_url(anchor.href, page_url=page_url)
        if not original_url:
            continue
        if fallback is None:
            fallback = (anchor, original_url)
        if _is_title_text(anchor.text):
            return anchor, original_url
    return fallback


def _pagination_state(
    anchors: list[_AnchorOccurrence],
    *,
    page_url: str,
) -> tuple[int, int, bool]:
    parsed_page = urlparse(page_url)
    host = (parsed_page.hostname or "").casefold()
    path = parsed_page.path.rstrip("/")
    tail = path.rsplit("/", 1)[-1]
    if tail.isdigit():
        current_page = int(tail)
        root_path = path.rsplit("/", 1)[0]
    else:
        current_page = 1
        root_path = path

    pages = {1, current_page}
    for anchor in anchors:
        absolute = urljoin(page_url, anchor.href)
        parsed = urlparse(absolute)
        if (parsed.hostname or "").casefold() != host:
            continue
        candidate = parsed.path.rstrip("/")
        if candidate == root_path:
            pages.add(1)
            continue
        prefix = f"{root_path}/"
        if not candidate.startswith(prefix):
            continue
        suffix = candidate[len(prefix) :]
        if suffix.isdigit():
            pages.add(int(suffix))

    return current_page, max(pages), current_page + 1 in pages


def parse_immmo_search_page(html: str, *, page_url: str) -> ImmmoPage:
    parser = _VisibleStreamParser()
    parser.feed(html)
    page_text = parser.text

    count_match = LIVE_COUNT_RE.search(page_text)
    reported_count = None
    count_is_lower_bound = False
    if count_match:
        reported_count = int(count_match.group("count").replace(".", ""))
        count_is_lower_bound = bool(count_match.group("lower"))

    result_headings: list[tuple[_HeadingOccurrence, re.Match[str]]] = []
    for heading in sorted(parser.headings, key=lambda item: item.start):
        match = RESULT_HEADING_RE.match(heading.text)
        if match is not None:
            result_headings.append((heading, match))

    anchors = sorted(parser.anchors, key=lambda item: item.start)
    items_by_url: dict[str, RawProperty] = {}
    cards_parsed = 0

    for index, (heading, heading_match) in enumerate(result_headings):
        segment_start = heading.start
        segment_end = (
            result_headings[index + 1][0].start
            if index + 1 < len(result_headings)
            else len(page_text)
        )
        chosen = _select_original_anchor(
            anchors,
            segment_start=heading.end,
            segment_end=segment_end,
            page_url=page_url,
        )
        if chosen is None:
            continue
        anchor, original_url = chosen
        cards_parsed += 1

        card_text = page_text[segment_start:segment_end]
        facts = LOCATION_AREA_RE.search(card_text)
        if facts is not None:
            postal_code = facts.group("plz")
            city = _clean_text(facts.group("city")).strip(" ,")
            living_area = _decimal(facts.group("area"))
        else:
            postal_code = heading_match.group("plz")
            city = _clean_text(heading_match.group("city")).strip(" ,") or None
            living_area = None

        price_match = PRICE_RE.search(card_text)
        host = (urlparse(original_url).hostname or "").casefold()
        title = _clean_text(anchor.text) if _is_title_text(anchor.text) else heading.text

        items_by_url[original_url] = RawProperty(
            source_listing_id=_source_id(original_url),
            url=original_url,
            title=title[:500],
            description=None,
            price_eur=_decimal(price_match.group(1)) if price_match else None,
            living_area_m2=living_area,
            plot_area_m2=_plot_area(card_text),
            postal_code=postal_code,
            city=city,
            raw_payload={
                "format": "immmo-search-discovery-v6",
                "original_host": host,
                "discovery_url": page_url,
                "source_postal_code": postal_code,
                "source_heading_kind": _clean_text(heading_match.group("kind")),
            },
        )

    current_page, pagination_max_page, has_next_page = _pagination_state(
        anchors,
        page_url=page_url,
    )
    return ImmmoPage(
        list(items_by_url.values()),
        reported_count,
        count_is_lower_bound,
        len(result_headings),
        cards_parsed,
        current_page,
        pagination_max_page,
        has_next_page,
    )


def _validate_page_quality(
    page: ImmmoPage,
    *,
    shard_key: str,
    page_number: int,
) -> None:
    if page.cards_seen == 0:
        raise RuntimeError(
            f"IMMMO returned no result cards for shard {shard_key!r} page {page_number}"
        )
    if page.cards_parsed != page.cards_seen:
        raise RuntimeError(
            f"IMMMO URL discovery incomplete for shard {shard_key!r} page {page_number}: "
            f"parsed {page.cards_parsed}/{page.cards_seen} visible cards"
        )
    if page.has_next_page and page.cards_seen < math.ceil(PAGE_SIZE * 0.75):
        raise RuntimeError(
            f"IMMMO non-terminal page unexpectedly short for shard {shard_key!r} "
            f"page {page_number}: saw {page.cards_seen} cards"
        )
    if not page.items:
        raise RuntimeError(
            f"IMMMO returned no unique listing URLs for shard {shard_key!r} page {page_number}"
        )

    with_plz = sum(item.postal_code is not None for item in page.items)
    if with_plz / len(page.items) < 0.90:
        raise RuntimeError(
            f"IMMMO location quality too low for shard {shard_key!r} page {page_number}: "
            f"PLZ {with_plz}/{len(page.items)}"
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
        initial_reported_count: int | None = None
        latest_reported_count: int | None = None
        count_is_lower_bound = False
        pages_fetched = 0
        cards_seen = 0
        cards_parsed = 0
        result_cap_hit = False
        terminal_reached = False
        observed_max_page = 1
        page_number = 1

        def progress_cursor() -> dict[str, Any]:
            return {
                "newest_ids": list(items_by_id)[:100],
                "discovery_cards_seen": cards_seen,
                "discovery_cards_parsed": cards_parsed,
                "discovery_initial_reported": initial_reported_count,
                "discovery_latest_reported": latest_reported_count,
                "discovery_observed_max_page": observed_max_page,
                "discovery_terminal_reached": terminal_reached,
            }

        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=self.timeout_seconds,
                follow_redirects=True,
            ) as client:
                while True:
                    if page_number > 1:
                        await self._sleep()
                    response = await self._get(client, self._page_url(base_url, page_number))
                    page = parse_immmo_search_page(response.text, page_url=str(response.url))
                    if page_number == 1 and page.reported_count is None:
                        raise RuntimeError(f"IMMMO result count missing for shard {shard.key!r}")

                    if page.reported_count is not None:
                        latest_reported_count = page.reported_count
                        if initial_reported_count is None:
                            initial_reported_count = page.reported_count
                    count_is_lower_bound = count_is_lower_bound or page.count_is_lower_bound
                    observed_max_page = max(observed_max_page, page.pagination_max_page)

                    _validate_page_quality(page, shard_key=shard.key, page_number=page_number)
                    items_by_id.update({item.source_listing_id: item for item in page.items})
                    pages_fetched += 1
                    cards_seen += page.cards_seen
                    cards_parsed += page.cards_parsed

                    if not reconciliation:
                        if page_number >= self.incremental_pages or not page.has_next_page:
                            break
                    else:
                        if count_is_lower_bound or observed_max_page > self.hard_max_pages_per_shard:
                            result_cap_hit = True
                        if not page.has_next_page:
                            terminal_reached = True
                            break
                        if page_number >= self.hard_max_pages_per_shard:
                            result_cap_hit = True
                            break

                    page_number += 1
        except SourceFetchError:
            raise
        except Exception as exc:
            raise SourceFetchError(
                f"{type(exc).__name__}: {exc}",
                pages_fetched=pages_fetched,
                items_seen=len(items_by_id),
                source_reported_count=initial_reported_count,
                next_cursor=progress_cursor(),
            ) from exc

        benchmark_count = latest_reported_count or initial_reported_count or 0
        count_tolerance = max(PAGE_SIZE * 2, math.ceil(benchmark_count * 0.01))
        count_delta = cards_seen - benchmark_count
        count_plausible = benchmark_count > 0 and abs(count_delta) <= count_tolerance
        coverage_complete = (
            reconciliation
            and terminal_reached
            and not result_cap_hit
            and cards_seen == cards_parsed
            and count_plausible
        )

        cursor = progress_cursor()
        cursor["discovery_count_delta"] = count_delta
        cursor["discovery_count_tolerance"] = count_tolerance
        return SourceBatch(
            items=list(items_by_id.values()),
            next_cursor=cursor,
            source_reported_count=initial_reported_count,
            coverage_complete=coverage_complete,
            result_cap_hit=result_cap_hit,
            pages_fetched=pages_fetched,
        )
