from __future__ import annotations

import asyncio
import math
import random
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from app.property_heating import merge_heating_into_payload
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
from app.sources.property.kleinanzeigen_detail_de import parse_kleinanzeigen_house_detail
from app.sources.property.preview import card_thumbnail_url

BASE_URL = "https://www.kleinanzeigen.de"
SEARCH_ROOT = f"{BASE_URL}/s-haus-kaufen/anzeige:angebote/c208"
PAGE_SIZE = 25
DEFAULT_FRONTIER_PAGES = 12
DEFAULT_HARD_MAX_PAGES = 40
REGIONAL_FRONTIER_PAGES = 3

# Public regional offer routes checked against Kleinanzeigen pages on 2026-10-09.
# Explicit pilot only: no change to production scheduled national frontier.
# More regions/price filters require separately validated public routes.
REGIONAL_PILOT: tuple[tuple[str, str, str], ...] = (
    ("sachsen", "3799", "Sachsen"),
    ("thueringen", "3548", "Thüringen"),
    ("brandenburg", "7711", "Brandenburg"),
    ("nordrhein-westfalen", "928", "Nordrhein-Westfalen"),
)
REGIONAL_PILOT_BY_KEY = {
    key: (code, label) for key, code, label in REGIONAL_PILOT
}

_AD_PATH_RE = re.compile(
    r"^/s-anzeige/[^/?#]+/(?P<listing_id>\d+)-208-\d+/?$",
    re.IGNORECASE,
)
_COUNT_RE = re.compile(
    r"Häuser\s+zum\s+Kauf(?:\s+in\s+.+?)?\s+"
    r"[\d.]+\s*-\s*[\d.]+\s+von\s+(?P<count>[\d.]+)\s+Ergebnissen",
    re.IGNORECASE,
)
_LOCATION_RE = re.compile(r"^(?P<postal>\d{5})\s+(?P<city>.+)$")
_PRICE_RE = re.compile(r"^(?P<price>[\d.]+(?:,\d{1,2})?)\s*€(?:\s*VB)?$", re.IGNORECASE)
_LIVING_RE = re.compile(
    r"^(?P<living>[\d.]+(?:,\d+)?)\s*m(?:²|2)"
    r"(?:\s*[·|]\s*[\d.,]+\s*Zi\.)?(?:\s*[·|].*)?$",
    re.IGNORECASE,
)
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_ALLOWED_HOSTS = {"kleinanzeigen.de", "www.kleinanzeigen.de"}


@dataclass(frozen=True, slots=True)
class KleinanzeigenPage:
    items: list[RawProperty]
    source_reported_count: int
    max_page: int
    cards_seen: int
    cards_parsed: int
    out_of_budget_cards: int


def _canonical_ad_url(value: str, *, page_url: str) -> tuple[str, str] | None:
    absolute = urljoin(page_url, value)
    parsed = urlparse(absolute)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme not in {"http", "https"} or host not in _ALLOWED_HOSTS:
        return None
    match = _AD_PATH_RE.match(parsed.path)
    if match is None:
        return None
    canonical = urlunparse(("https", "www.kleinanzeigen.de", parsed.path.rstrip("/"), "", "", ""))
    return canonical, match.group("listing_id")


def _ad_anchor(card: _Node, *, page_url: str) -> tuple[_Node, str, str] | None:
    candidates: list[tuple[_Node, str, str]] = []
    for node in card.walk():
        if node.tag != "a":
            continue
        detail = _canonical_ad_url(node.attrs.get("href", ""), page_url=page_url)
        if detail is None:
            continue
        url, listing_id = detail
        candidates.append((node, url, listing_id))
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item[0].text()))


def _short_text_candidates(card: _Node) -> list[str]:
    values: set[str] = set()
    for node in card.walk():
        value = _clean_text(node.text())
        if value and len(value) <= 180:
            values.add(value)
    return sorted(values, key=len)


def _location(card: _Node) -> tuple[str, str] | None:
    for value in _short_text_candidates(card):
        match = _LOCATION_RE.match(value)
        if match is None:
            continue
        city = match.group("city").strip()
        if (
            city
            and len(city) <= 100
            and "€" not in city
            and "m²" not in city
            and "Zi." not in city
        ):
            return match.group("postal"), city
    return None


def _price(card: _Node) -> Decimal | None:
    for value in _short_text_candidates(card):
        match = _PRICE_RE.match(value)
        if match is not None:
            return _decimal(match.group("price"))
    return None


def _living_area(card: _Node) -> Decimal | None:
    for value in _short_text_candidates(card):
        match = _LIVING_RE.match(value)
        if match is not None:
            return _decimal(match.group("living"))
    return None


def parse_kleinanzeigen_search_page(
    html: str,
    *,
    page_url: str,
) -> KleinanzeigenPage:
    parser = _DOMParser()
    parser.feed(html)
    text = parser.root.text()
    count_match = _COUNT_RE.search(text)
    if count_match is None:
        raise ValueError("Kleinanzeigen house result count is missing")
    source_reported_count = int(count_match.group("count").replace(".", ""))
    max_page = max(1, math.ceil(source_reported_count / PAGE_SIZE))

    cards: list[_Node] = []
    seen_ids: set[str] = set()
    for node in parser.root.walk():
        if node.tag != "article":
            continue
        anchor = _ad_anchor(node, page_url=page_url)
        if anchor is None:
            continue
        listing_id = anchor[2]
        if listing_id in seen_ids:
            continue
        seen_ids.add(listing_id)
        cards.append(node)

    items: list[RawProperty] = []
    cards_parsed = 0
    out_of_budget_cards = 0
    for card in cards:
        detail = _ad_anchor(card, page_url=page_url)
        if detail is None:
            continue
        anchor, url, listing_id = detail
        title = _clean_text(anchor.text())
        location = _location(card)
        if not title or location is None:
            continue
        cards_parsed += 1
        postal_code, city = location
        price = _price(card)
        living = _living_area(card)
        thumbnail_url = card_thumbnail_url(card, page_url=page_url)

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
                plot_area_m2=None,
                postal_code=postal_code,
                city=city,
                raw_payload={
                    "format": "kleinanzeigen-public-frontier-v1",
                    "country_code": "DE",
                    "discovery_url": page_url,
                    "source_postal_code": postal_code,
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
        )

    return KleinanzeigenPage(
        items=items,
        source_reported_count=source_reported_count,
        max_page=max_page,
        cards_seen=len(cards),
        cards_parsed=cards_parsed,
        out_of_budget_cards=out_of_budget_cards,
    )


def _validate_page(page: KleinanzeigenPage, *, page_number: int) -> None:
    if page.source_reported_count and page.cards_seen == 0:
        raise RuntimeError(
            f"Kleinanzeigen returned no identifiable house cards on non-empty page {page_number}"
        )
    if page.cards_seen != page.cards_parsed:
        raise RuntimeError(
            f"Kleinanzeigen card parsing incomplete on page {page_number}: "
            f"parsed {page.cards_parsed}/{page.cards_seen}"
        )


class KleinanzeigenGermanyPropertySource(PropertySource):
    """Bounded newest-first public house frontier without disappearance authority."""

    name = "kleinanzeigen-de"

    def __init__(
        self,
        *,
        request_delay_seconds: float = 3.0,
        frontier_pages: int = DEFAULT_FRONTIER_PAGES,
        hard_max_pages: int = DEFAULT_HARD_MAX_PAGES,
        timeout_seconds: float = 30.0,
        regional_pilot: bool = False,
        regional_expansion: bool = False,
        detail_checks_per_shard: int = 0,
    ) -> None:
        if not 0 <= detail_checks_per_shard <= 8:
            raise ValueError("Public detail checks must be explicitly capped at 8 per shard")
        if regional_pilot and regional_expansion:
            raise ValueError("Regional pilot and expansion modes are mutually exclusive")
        self.request_delay_seconds = max(2.0, request_delay_seconds)
        self.frontier_pages = max(1, frontier_pages)
        self.hard_max_pages = max(self.frontier_pages, hard_max_pages)
        self.timeout_seconds = timeout_seconds
        self.regional_pilot = regional_pilot
        self.regional_expansion = regional_expansion
        self.detail_checks_per_shard = detail_checks_per_shard
        self._requests_made = 0

    def default_shards(self) -> list[SourceShardSpec]:
        national = SourceShardSpec(
            key="de-newest-frontier",
            params={"country_code": "DE"},
            result_cap=self.hard_max_pages * PAGE_SIZE,
            priority=50,
        )
        regional = [
            SourceShardSpec(
                key=f"de-region-{region}",
                params={"country_code": "DE", "region_key": region},
                result_cap=self.hard_max_pages * PAGE_SIZE,
                priority=50,
            )
            for region, _code, _label in REGIONAL_PILOT
        ]
        if self.regional_pilot:
            return regional
        if self.regional_expansion:
            # Keep the original source shard enabled and its persisted cursor intact.
            return [national, *regional]
        return [national]

    @staticmethod
    def _page_url(page: int, *, region_key: str | None = None) -> str:
        if region_key is not None:
            code, _label = REGIONAL_PILOT_BY_KEY[region_key]
            root = f"{BASE_URL}/s-haus-kaufen/{region_key}/anzeige:angebote"
            if page <= 1:
                return f"{root}/c208l{code}"
            return f"{root}/seite:{page}/c208l{code}"
        if page <= 1:
            return SEARCH_ROOT
        return f"{BASE_URL}/s-haus-kaufen/seite:{page}/anzeige:angebote/c208"

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
                    raise RuntimeError(f"Kleinanzeigen redirected off-site: {response.url!s}")
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                if status in {401, 403}:
                    raise SourceFetchError(
                        f"Kleinanzeigen access gate HTTP {status}",
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

    async def _enrich_public_detail(
        self, client: httpx.AsyncClient, item: RawProperty,
    ) -> bool:
        """Opt-in public GET for an already discovered budget-eligible house.

        No retry or bypass on restricted pages; no text, seller data or contact
        details are persisted. A review of provider terms is required BEFORE
        an operator enables detail checks in a manual run.
        """
        await self._sleep()
        self._requests_made += 1
        try:
            response = await client.get(item.url, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise SourceFetchError(
                f"Kleinanzeigen detail access failed: {type(exc).__name__}",
                halt_source=True,
            ) from exc
        if response.status_code in {401, 403, 429, 503}:
            raise SourceFetchError(
                f"Kleinanzeigen detail access restricted ({response.status_code})",
                halt_source=True,
            )
        if (
            response.status_code != 200
            or str(response.url) != item.url
            or "text/html" not in response.headers.get("content-type", "").casefold()
            or len(response.content) > 4_000_000
        ):
            item.raw_payload["detail_enrichment_reason"] = "unavailable_or_redirected"
            return False
        if re.search(
            r"captcha|security verification|zugriff (?:vorübergehend )?eingeschränkt",
            response.text[:2000], re.IGNORECASE,
        ):
            raise SourceFetchError(
                "Kleinanzeigen detail human-verification boundary", halt_source=True,
            )
        try:
            facts = parse_kleinanzeigen_house_detail(
                response.text, url=item.url,
                expected_listing_id=item.source_listing_id,
            )
        except ValueError:
            item.raw_payload["detail_enrichment_reason"] = "identity_or_evidence_invalid"
            return False
        if facts.plot_area_m2 is not None:
            item.plot_area_m2 = facts.plot_area_m2
            item.raw_payload["plot_area_evidence"] = facts.plot_evidence
            item.raw_payload["plot_area_source"] = "kleinanzeigen_detail"
        item.raw_payload = merge_heating_into_payload(item.raw_payload, facts.heating)
        if not facts.heating.types and facts.plot_area_m2 is None:
            item.raw_payload["detail_enrichment_reason"] = "no_verified_fields"
            return False
        item.raw_payload["detail_enriched"] = True
        item.raw_payload["detail_source"] = "kleinanzeigen_public_house_detail"
        return True

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        del cursor, reconciliation
        region_key = shard.params.get("region_key")
        if region_key is not None:
            if not (self.regional_pilot or self.regional_expansion):
                raise ValueError("Regional shard requires enabled regional mode")
            if region_key not in REGIONAL_PILOT_BY_KEY:
                raise ValueError("Unrecognized configured regional shard")
        elif self.regional_pilot:
            raise ValueError("Regional-only pilot cannot fetch the national shard")
        items_by_id: dict[str, RawProperty] = {}
        pages_fetched = 0
        cards_seen = 0
        cards_parsed = 0
        out_of_budget_cards = 0
        source_reported_count: int | None = None
        source_max_page = 1
        detail_checked = 0
        detail_verified = 0

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
                target_pages = (
                    REGIONAL_FRONTIER_PAGES if region_key is not None else self.frontier_pages
                )
                for page_number in range(1, target_pages + 1):
                    response = await self._get(
                        client, self._page_url(page_number, region_key=region_key)
                    )
                    if region_key is not None:
                        code, label = REGIONAL_PILOT_BY_KEY[region_key]
                        # Fail closed if a stale or invalid region is silently redirected
                        # to the nationwide frontier. A 200 response is insufficient.
                        path = response.url.path
                        if (
                            f"/{region_key}/" not in path
                            or not path.endswith(f"/c208l{code}")
                            or f"Häuser zum Kauf in {label}" not in response.text
                        ):
                            raise SourceFetchError(
                                "Kleinanzeigen regional search scope was lost",
                                halt_source=True,
                            )
                    page = parse_kleinanzeigen_search_page(
                        response.text,
                        page_url=str(response.url),
                    )
                    _validate_page(page, page_number=page_number)
                    source_reported_count = (
                        page.source_reported_count
                        if source_reported_count is None
                        else max(source_reported_count, page.source_reported_count)
                    )
                    source_max_page = max(source_max_page, page.max_page)
                    items_by_id.update({item.source_listing_id: item for item in page.items})
                    pages_fetched += 1
                    cards_seen += page.cards_seen
                    cards_parsed += page.cards_parsed
                    out_of_budget_cards += page.out_of_budget_cards
                    if page_number >= page.max_page:
                        break
                # This feature is deliberately off in scheduled runs.
                # Only explicit manual operator opt-in can add detail requests.
                for item in list(items_by_id.values())[:self.detail_checks_per_shard]:
                    try:
                        verified = await self._enrich_public_detail(client, item)
                    except SourceFetchError:
                        detail_checked += 1
                        raise
                    detail_checked += 1
                    if verified:
                        detail_verified += 1
        except Exception as exc:
            if isinstance(exc, SourceFetchError):
                exc.pages_fetched = pages_fetched
                exc.items_seen = len(items_by_id)
                exc.source_reported_count = source_reported_count
                exc.partial_items = list(items_by_id.values())
                exc.next_cursor = {
                    "frontier_cards_seen": cards_seen,
                    "frontier_cards_parsed": cards_parsed,
                    "frontier_out_of_budget_cards": out_of_budget_cards,
                    "frontier_source_max_page": source_max_page,
                    "country_code": "DE",
                    **({"region_key": region_key} if region_key else {}),
                }
                raise
            raise SourceFetchError(
                f"Kleinanzeigen frontier failed: {type(exc).__name__}: {exc}",
                pages_fetched=pages_fetched,
                items_seen=len(items_by_id),
                source_reported_count=source_reported_count,
                partial_items=list(items_by_id.values()),
                next_cursor={
                    "frontier_cards_seen": cards_seen,
                    "frontier_cards_parsed": cards_parsed,
                    "frontier_out_of_budget_cards": out_of_budget_cards,
                    "frontier_source_max_page": source_max_page,
                    "country_code": "DE",
                    **({"region_key": region_key} if region_key else {}),
                },
            ) from exc

        # The source contains orders of magnitude more listings than this newest-first
        # frontier. It must never gain disappearance/reconciliation authority.
        capped = source_max_page > pages_fetched
        return SourceBatch(
            items=list(items_by_id.values()),
            next_cursor={
                "newest_ids": list(items_by_id)[:100],
                "frontier_cards_seen": cards_seen,
                "frontier_cards_parsed": cards_parsed,
                "frontier_out_of_budget_cards": out_of_budget_cards,
                "frontier_source_max_page": source_max_page,
                "detail_checked": detail_checked,
                "detail_verified": detail_verified,
                "country_code": "DE",
                **({"region_key": region_key} if region_key else {}),
            },
            source_reported_count=source_reported_count,
            coverage_complete=False,
            result_cap_hit=capped,
            pages_fetched=pages_fetched + detail_checked,
        )
