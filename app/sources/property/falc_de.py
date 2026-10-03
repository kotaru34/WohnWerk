from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from app.property_heating import (
    extract_heating_evidence_from_html,
    merge_heating_into_payload,
)
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

BASE_URL = "https://www.falcimmo.de"
SEARCH_ROOT = f"{BASE_URL}/haeuser-zum-kauf.html"
DEFAULT_FRONTIER_PAGES = 8
DEFAULT_HARD_MAX_PAGES = 40

_ALLOWED_HOSTS = {"falcimmo.de", "www.falcimmo.de"}
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_DETAIL_PATH_RE = re.compile(r"^/immobilie/(?P<slug>[a-z0-9][a-z0-9-]*)\.html$", re.IGNORECASE)
_COUNT_RE = re.compile(r"(?P<count>[\d.]+)\s+Immobilien\s+gefunden", re.IGNORECASE)
_LOCATION_RE = re.compile(
    r"\b(?P<plz>\d{5})\s+(?P<city>.+?)\s+-\s+Deutschland\b",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(
    r"\bKaufpreis\s*(?P<price>[\d.]+(?:,\d{1,2})?)\s*€",
    re.IGNORECASE,
)
_LIVING_RE = re.compile(
    r"\bWohnfläche\s*(?P<area>[\d.]+(?:,\d+)?)\s*m(?:²|2)",
    re.IGNORECASE,
)
_PLOT_RE = re.compile(
    r"\bGrundstücksfläche\s*(?P<area>[\d.]+(?:,\d+)?)\s*m(?:²|2)",
    re.IGNORECASE,
)
_OBJECT_ID_RE = re.compile(r"\bObjektnr\.\s*(?P<listing_id>FALC-[A-Z0-9-]+)\b", re.IGNORECASE)
_UNAVAILABLE_RE = re.compile(r"^\s*(?:reserviert|verkauft)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class FalcCandidate:
    url: str
    title: str
    price_eur: Any
    living_area_m2: Any
    plot_area_m2: Any
    postal_code: str
    city: str
    source_location: str
    thumbnail_url: str | None


@dataclass(frozen=True, slots=True)
class FalcPage:
    candidates: list[FalcCandidate]
    source_reported_count: int | None
    cards_seen: int
    cards_parsed: int
    unavailable_cards: int
    price_unknown_cards: int
    out_of_budget_cards: int


def _canonical_detail_url(value: str, *, page_url: str) -> str | None:
    absolute = urljoin(page_url, value)
    parsed = urlparse(absolute)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or host not in _ALLOWED_HOSTS:
        return None
    if _DETAIL_PATH_RE.match(parsed.path) is None:
        return None
    return urlunparse(("https", "www.falcimmo.de", parsed.path, "", "", ""))


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


def _card_for_anchor(anchor: _Node, *, page_url: str, detail_url: str) -> _Node | None:
    node = anchor.parent
    fallback: _Node | None = None
    for _ in range(16):
        if node is None or node.tag == "document":
            break
        details = {url for _child, url in _detail_anchors(node, page_url=page_url)}
        if len(details) > 1:
            break
        text = node.text()
        if (
            details == {detail_url}
            and _LOCATION_RE.search(text)
            and (_PRICE_RE.search(text) or "Kaufpreis" in text)
        ):
            fallback = node
            if "Objektart" in text and (_LIVING_RE.search(text) or "Wohnfläche" in text):
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


def parse_falc_search_page(html: str, *, page_url: str) -> FalcPage:
    parser = _DOMParser()
    parser.feed(html)
    page_text = parser.root.text()

    count_match = _COUNT_RE.search(page_text)
    source_reported_count = (
        int(count_match.group("count").replace(".", "")) if count_match else None
    )

    cards: list[tuple[_Node, str]] = []
    seen_urls: set[str] = set()
    for anchor, url in _detail_anchors(parser.root, page_url=page_url):
        if url in seen_urls:
            continue
        card = _card_for_anchor(anchor, page_url=page_url, detail_url=url)
        if card is None:
            continue
        seen_urls.add(url)
        cards.append((card, url))

    candidates: list[FalcCandidate] = []
    cards_parsed = unavailable_cards = price_unknown_cards = out_of_budget_cards = 0

    for card, url in cards:
        text = card.text()
        location = _LOCATION_RE.search(text)
        title = _title_for_card(card, page_url=page_url, detail_url=url)
        if location is None or not title:
            continue
        cards_parsed += 1

        if _UNAVAILABLE_RE.search(title):
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
        source_location = f"{location.group('plz')} {city}".strip()
        candidates.append(
            FalcCandidate(
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
                city=city,
                source_location=source_location,
                thumbnail_url=card_thumbnail_url(card, page_url=page_url),
            )
        )

    return FalcPage(
        candidates=candidates,
        source_reported_count=source_reported_count,
        cards_seen=len(cards),
        cards_parsed=cards_parsed,
        unavailable_cards=unavailable_cards,
        price_unknown_cards=price_unknown_cards,
        out_of_budget_cards=out_of_budget_cards,
    )


def parse_falc_detail_identity(html: str) -> str:
    parser = _DOMParser()
    parser.feed(html)
    match = _OBJECT_ID_RE.search(parser.root.text())
    if match is None:
        raise ValueError("FALC detail page is missing Objektnr.")
    return match.group("listing_id").upper()


def _validate_page(page: FalcPage, *, page_number: int) -> None:
    if page.source_reported_count and page.cards_seen == 0:
        raise RuntimeError(f"FALC returned no identifiable cards on non-empty page {page_number}")
    if page.cards_seen != page.cards_parsed:
        raise RuntimeError(
            f"FALC card parsing incomplete on page {page_number}: "
            f"parsed {page.cards_parsed}/{page.cards_seen}"
        )


class FalcGermanyPropertySource(PropertySource):
    """Bounded public FALC Germany house-sale frontier."""

    name = "falc-de"

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
                priority=78,
            )
        ]

    @staticmethod
    def _page_url(page: int) -> str:
        if page <= 1:
            return SEARCH_ROOT
        return f"{SEARCH_ROOT}?page_n47={page}"

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
                    raise RuntimeError(f"FALC redirected off-site: {response.url!s}")
                if response.status_code in {401, 403}:
                    raise SourceFetchError(
                        f"FALC access gate HTTP {response.status_code}",
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

    async def _materialize_candidate(
        self,
        client: httpx.AsyncClient,
        candidate: FalcCandidate,
        *,
        discovery_url: str,
    ) -> RawProperty:
        response = await self._get(client, candidate.url)
        listing_id = parse_falc_detail_identity(response.text)
        payload = {
            "format": "falc-de-public-frontier-v1",
            "country_code": "DE",
            "discovery_url": discovery_url,
            "source_location": candidate.source_location,
            "source_object_number": listing_id,
            "identity_stable": True,
            "frontier_only": True,
            **(
                {
                    "thumbnail_url": candidate.thumbnail_url,
                    "thumbnail_semantics": "source_search_card",
                }
                if candidate.thumbnail_url
                else {}
            ),
        }
        payload = merge_heating_into_payload(
            payload,
            extract_heating_evidence_from_html(response.text),
        )
        return RawProperty(
            source_listing_id=listing_id,
            url=candidate.url,
            title=candidate.title,
            description=None,
            price_eur=candidate.price_eur,
            living_area_m2=candidate.living_area_m2,
            plot_area_m2=candidate.plot_area_m2,
            postal_code=candidate.postal_code,
            city=candidate.city or None,
            raw_payload=payload,
        )

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
        detail_identity_failures = 0
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
                    page = parse_falc_search_page(response.text, page_url=str(response.url))
                    _validate_page(page, page_number=page_number)
                    source_reported_count = max(
                        source_reported_count or 0,
                        page.source_reported_count or 0,
                    ) or None
                    pages_fetched += 1
                    cards_seen += page.cards_seen
                    cards_parsed += page.cards_parsed
                    unavailable_cards += page.unavailable_cards
                    price_unknown_cards += page.price_unknown_cards
                    out_of_budget_cards += page.out_of_budget_cards

                    for candidate in page.candidates:
                        try:
                            item = await self._materialize_candidate(
                                client,
                                candidate,
                                discovery_url=str(response.url),
                            )
                        except ValueError as exc:
                            detail_identity_failures += 1
                            raise RuntimeError(
                                f"FALC stable identity missing for {candidate.url}"
                            ) from exc
                        items_by_id[item.source_listing_id] = item
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
                    "detail_identity_failures": detail_identity_failures,
                }
                raise
            raise SourceFetchError(
                f"FALC frontier failed: {type(exc).__name__}: {exc}",
                pages_fetched=pages_fetched,
                items_seen=len(items_by_id),
                source_reported_count=source_reported_count,
                partial_items=list(items_by_id.values()),
                next_cursor={
                    "country_code": "DE",
                    "frontier_cards_seen": cards_seen,
                    "frontier_cards_parsed": cards_parsed,
                    "detail_identity_failures": detail_identity_failures,
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
                "detail_identity_failures": detail_identity_failures,
            },
            source_reported_count=source_reported_count,
            coverage_complete=False,
            result_cap_hit=bool(
                source_reported_count is not None
                and source_reported_count > len(items_by_id)
            ),
            pages_fetched=pages_fetched,
        )
