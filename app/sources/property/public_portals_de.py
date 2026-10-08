"""Account-free, bounded German house discovery on independent public portals.

Only public search-card facts are retained. Both frontiers are non-authoritative:
a missing listing must never be interpreted as sold or removed.
"""
from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from app.sources.base import PropertySource, RawProperty, SourceBatch, SourceFetchError, SourceShardSpec
from app.sources.property.germany import (
    GERMANY_PROPERTY_MAX_PRICE_EUR,
    GERMANY_PROPERTY_MIN_PRICE_EUR,
)
from app.sources.property.immmo import _DOMParser, _Node, _clean_text, _decimal


@dataclass(frozen=True, slots=True)
class Portal:
    name: str
    base_url: str
    search_path: str
    detail_prefix: str


OHNE_MAKLER = Portal(
    "ohne-makler-de", "https://www.ohne-makler.net",
    "/immobilien/haus-immobilien/", "/immobilie/",
)
IMMOBILIEN_DE = Portal(
    "immobilien-de", "https://www.immobilien.de", "/kaufen/haus/", "/expose/",
)

_PRICE = re.compile(r"(?<!\w)([\d.]+(?:,\d{1,2})?)\s*€")
_POSTAL = re.compile(r"(?<!\d)(\d{5})\s+([A-ZÄÖÜa-zäöüß][^\d€]{1,75})")
_AREA = re.compile(r"(?<!\d)(\d{1,4}(?:[.,]\d{1,2})?)\s*m(?:²|2)\b", re.I)
_BLOCKED = re.compile(
    r"(?:captcha|security verification|zugriff (?:vorübergehend )?eingeschränkt)",
    re.I,
)


def _canonical_listing(href: str, *, page_url: str, portal: Portal) -> tuple[str, str] | None:
    parsed = urlsplit(urljoin(page_url, href))
    base = urlsplit(portal.base_url)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").casefold().removeprefix("www.")
        != (base.hostname or "").casefold().removeprefix("www.")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
        return None
    path = parsed.path.rstrip("/") + "/"
    pattern = re.escape(portal.detail_prefix) + r"(\d+)/"
    match = re.fullmatch(pattern, path)
    if match is None:
        return None
    listing_id = match.group(1)
    return f"{portal.base_url}{portal.detail_prefix}{listing_id}/", listing_id


def _card_for_anchor(anchor: _Node, *, page_url: str, portal: Portal) -> _Node | None:
    node: _Node | None = anchor
    for _ in range(9):
        if node is None or node.tag == "document":
            break
        ids = {
            match[1]
            for child in node.walk()
            if child.tag == "a"
            if (match := _canonical_listing(
                child.attrs.get("href", ""), page_url=page_url, portal=portal
            )) is not None
        }
        if len(ids) > 1:
            return None
        text = node.text()
        if _PRICE.search(text) and _POSTAL.search(text):
            return node
        node = node.parent
    return None


def parse_public_portal_page(html: str, *, page_url: str, portal: Portal) -> tuple[list[RawProperty], int]:
    parser = _DOMParser()
    parser.feed(html)
    output: dict[str, RawProperty] = {}
    seen: set[str] = set()

    for anchor in parser.root.walk():
        if anchor.tag != "a":
            continue
        match = _canonical_listing(anchor.attrs.get("href", ""), page_url=page_url, portal=portal)
        if match is None:
            continue
        url, listing_id = match
        if listing_id in seen:
            continue
        seen.add(listing_id)
        card = _card_for_anchor(anchor, page_url=page_url, portal=portal)
        if card is None:
            continue
        text = card.text()
        price_match = _PRICE.search(text)
        postcode_match = _POSTAL.search(text)
        if price_match is None or postcode_match is None:
            continue
        price = _decimal(price_match.group(1))
        if price is None or not (
            GERMANY_PROPERTY_MIN_PRICE_EUR <= price <= GERMANY_PROPERTY_MAX_PRICE_EUR
        ):
            continue

        title = _clean_text(anchor.text())
        # In some portals, the entire search card is one hyperlink.
        # Separate its title from the explicitly parsed price and location.
        if _PRICE.search(title) and _POSTAL.search(title):
            title = _clean_text(title[_PRICE.search(title).end():_POSTAL.search(title).start()])
        if len(title) < 7:
            title = _clean_text(text[price_match.end():postcode_match.start()])
        if not 7 <= len(title) <= 500:
            continue
        city = _clean_text(postcode_match.group(2)).strip(" ,-")
        if len(city) > 100:
            continue
        areas = [_decimal(value) for value in _AREA.findall(text)]
        output[listing_id] = RawProperty(
            source_listing_id=listing_id,
            url=url,
            title=title[:500],
            price_eur=price,
            postal_code=postcode_match.group(1),
            city=city or None,
            living_area_m2=areas[0] if areas else None,
            plot_area_m2=areas[1] if len(areas) > 1 else None,
            raw_payload={
                "format": "german-public-house-frontier-v1",
                "country_code": "DE",
                "identity_stable": True,
                "frontier_only": True,
                "discovery_url": page_url,
            },
        )
    return list(output.values()), len(seen)


class PublicGermanHouseSource(PropertySource):
    """Single-page discovery until live pagination and source terms are validated."""

    portal: Portal

    def __init__(self, *, delay_seconds: float = 3.0, timeout_seconds: float = 20.0) -> None:
        self.delay_seconds = max(2.0, delay_seconds)
        self.timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return self.portal.name

    def default_shards(self) -> list[SourceShardSpec]:
        return [SourceShardSpec(
            key="de-public-frontier",
            params={"country_code": "DE"},
            result_cap=50,
            priority=100,
        )]

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        del cursor
        if reconciliation or shard.key != "de-public-frontier":
            raise SourceFetchError("Public portal supports bounded discovery only")
        await asyncio.sleep(self.delay_seconds * random.uniform(0.85, 1.2))
        url = self.portal.base_url + self.portal.search_path
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
                headers={"User-Agent": "WohnWerk/0.4 (+https://wohnwerk.kotaru.lainlounge.org)",
                         "Accept": "text/html", "Accept-Language": "de-DE,de;q=0.9"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                if str(response.url) != url:
                    raise RuntimeError("Unexpected portal redirect")
                html = response.text
                if _BLOCKED.search(html[:2000]):
                    raise RuntimeError("Provider challenge or access restriction")
                items, seen = parse_public_portal_page(
                    html, page_url=url, portal=self.portal
                )
                if not seen:
                    raise RuntimeError("No identifiable listing cards; refusing empty success")
                return SourceBatch(
                    items=items,
                    source_reported_count=seen,
                    coverage_complete=False,
                    pages_fetched=1,
                    next_cursor={"country_code": "DE", "frontier_cards_seen": seen},
                )
        except (httpx.HTTPError, RuntimeError) as exc:
            raise SourceFetchError(
                f"{self.name}: public frontier unavailable ({type(exc).__name__})",
                pages_fetched=0, items_seen=0,
            ) from exc


class OhneMaklerGermanyPropertySource(PublicGermanHouseSource):
    portal = OHNE_MAKLER


class ImmobilienDeGermanyPropertySource(PublicGermanHouseSource):
    portal = IMMOBILIEN_DE
