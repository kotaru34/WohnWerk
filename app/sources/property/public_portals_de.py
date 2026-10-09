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

from app.sources.base import (
    PropertySource,
    RawProperty,
    SourceBatch,
    SourceFetchError,
    SourceShardSpec,
)
from app.sources.property.public_portal_detail_de import verify_public_house_detail
from app.sources.property.germany import (
    GERMANY_PROPERTY_MAX_PRICE_EUR,
    GERMANY_PROPERTY_MIN_PRICE_EUR,
)
from app.sources.property.immmo import _clean_text, _decimal, _DOMParser, _Node


@dataclass(frozen=True, slots=True)
class Portal:
    name: str
    base_url: str
    search_path: str
    detail_prefix: str


OHNE_MAKLER = Portal(
    "ohne-makler-de", "https://www.ohne-makler.net",
    "/immobilien/haus-kaufen/", "/immobilie/",
)
IMMOBILIEN_DE = Portal(
    "immobilien-de", "https://www.immobilien.de", "/kaufen/haus/", "/expose/",
)

_PRICE = re.compile(r"(?<!\w)([\d.]+(?:,\d{1,2})?)\s*€")
_ASKING_PRICE = re.compile(
    r"(?<!\w)([\d.]+(?:,\d{1,2})?)\s*€\s*Kaufpreis\b", re.IGNORECASE
)
_NOT_FOR_SALE = re.compile(
    r"\b(?:verkauft|reserviert|nicht mehr verfuegbar|nicht mehr verfügbar)\b",
    re.IGNORECASE,
)
_NOT_ACTUAL_PROPERTY = re.compile(
    r"\b(?:hauspreis ohne grundst[üu]ck|ohne baugrundst[üu]ck|"
    r"ohne grundst[üu]ck|auf (?:ihrem|einem) grundst[üu]ck|"
    r"auf pachtgrundst[üu]ck)\b",
    re.IGNORECASE,
)
_POSTAL = re.compile(r"(?<!\d)(\d{5})\s+([A-ZÄÖÜa-zäöüß][^\d€]{1,75})")
_AREA = re.compile(r"(?<!\d)(\d{1,4}(?:[.,]\d{1,2})?)\s*m(?:²|2)\b", re.IGNORECASE)
_BLOCKED = re.compile(
    r"(?:captcha|security verification|zugriff (?:vorübergehend )?eingeschränkt)",
    re.IGNORECASE,
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
    canonical_suffix = "/" if portal == OHNE_MAKLER else ""
    return f"{portal.base_url}{portal.detail_prefix}{listing_id}{canonical_suffix}", listing_id


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


def _title_from_card(
    card: _Node,
    *,
    listing_id: str,
    page_url: str,
    portal: Portal,
) -> str | None:
    """Choose a title-only link, not an image link or price/area boilerplate.

    Some providers render separate image and title anchors for the same listing;
    the first matching anchor is often an image without text. Reusing the entire
    card text as the title can produce 'Kaufpreis 1.039 €/m²' as a fake title.
    """
    for candidate in card.walk():
        if candidate.tag != "a":
            continue
        match = _canonical_listing(
            candidate.attrs.get("href", ""), page_url=page_url, portal=portal
        )
        if match is None or match[1] != listing_id:
            continue
        title = _clean_text(candidate.text())
        if _PRICE.search(title) and _POSTAL.search(title):
            start = _PRICE.search(title)
            end = _POSTAL.search(title)
            if start is None or end is None or end.start() <= start.end():
                continue
            title = _clean_text(title[start.end():end.start()])
        # Do not promote unlabeled numerical price metrics into property titles.
        if (not 7 <= len(title) <= 500 or "€" in title
                or title.casefold().startswith(("kaufpreis", "preis pro", "fläche", "zimmer"))):
            continue
        return title
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
        # €/m² values can appear before the asking price in page markup.
        # Immobilien.de labels the real asking price as "Kaufpreis".
        price_match = (
            _ASKING_PRICE.search(text) if portal == IMMOBILIEN_DE else _PRICE.search(text)
        )
        postcode_match = _POSTAL.search(text)
        if price_match is None or postcode_match is None:
            continue
        price = _decimal(price_match.group(1))
        if price is None or not (
            GERMANY_PROPERTY_MIN_PRICE_EUR <= price <= GERMANY_PROPERTY_MAX_PRICE_EUR
        ):
            continue

        title = _title_from_card(
            card, listing_id=listing_id, page_url=page_url, portal=portal
        )
        if title is None:
            continue
        # A live purchase frontier can retain sold/reserved ads and
        # build-only offers that do not include the land in the stated price.
        if _NOT_FOR_SALE.search(title) or _NOT_ACTUAL_PROPERTY.search(title):
            continue
        city = re.split(
            r"\b(?:Fläche|Zimmer|Baujahr|Wohnfläche|Grundstück|Kaufpreis)\b",
            _clean_text(postcode_match.group(2)), maxsplit=1, flags=re.IGNORECASE,
        )[0].strip(" ,-")
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
                # Public cards are discovery leads, not proof of a purchasable
                # existing house including the plot. Do not show unchecked
                # house-builder brochures in the candidate catalogue.
                "public_house_detail_required": True,
                "public_house_detail_verified": False,
            },
        )
    return list(output.values()), len(seen)


class PublicGermanHouseSource(PropertySource):
    """Single-page discovery until live pagination and source terms are validated."""

    portal: Portal

    def __init__(
        self,
        *,
        delay_seconds: float = 3.0,
        timeout_seconds: float = 20.0,
        verify_details: bool = False,
        max_detail_checks_per_shard: int = 8,
    ) -> None:
        if max_detail_checks_per_shard < 0 or max_detail_checks_per_shard > 10:
            raise ValueError("detail checks must be bounded to 0..10 per shard")
        self.delay_seconds = max(2.0, delay_seconds)
        self.timeout_seconds = timeout_seconds
        self.verify_details = verify_details
        self.max_detail_checks_per_shard = max_detail_checks_per_shard

    @property
    def name(self) -> str:
        return self.portal.name

    def frontier_paths(self) -> dict[str, str]:
        """Only operator-audited, explicitly enumerated public search pages."""
        return {"de-public-frontier": self.portal.search_path}

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=key,
                params={"country_code": "DE"},
                result_cap=50,
                priority=100 + order * 10,
            )
            for order, key in enumerate(self.frontier_paths())
        ]

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        del cursor
        path = self.frontier_paths().get(shard.key)
        if reconciliation or path is None:
            raise SourceFetchError("Public portal supports whitelisted bounded discovery only")
        await asyncio.sleep(self.delay_seconds * random.uniform(0.85, 1.2))
        url = self.portal.base_url + path
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
                detail_checked = 0
                detail_verified = 0
                # Never fetch details in raw-card inspection mode. The
                # visibility gate above keeps all such observations hidden.
                if self.verify_details:
                    for item in items[: self.max_detail_checks_per_shard]:
                        await asyncio.sleep(self.delay_seconds)
                        try:
                            detail = await client.get(item.url)
                        except httpx.HTTPError as exc:
                            raise SourceFetchError(
                                f"{self.name}: detail request failed ({type(exc).__name__})",
                                pages_fetched=1 + detail_checked,
                                items_seen=len(items),
                                partial_items=items,
                                halt_source=True,
                            ) from exc
                        detail_checked += 1
                        if detail.status_code in {403, 429, 503}:
                            raise SourceFetchError(
                                f"{self.name}: detail access restriction ({detail.status_code})",
                                pages_fetched=1 + detail_checked,
                                items_seen=len(items),
                                partial_items=items,
                                halt_source=True,
                            )
                        if (
                            detail.status_code != 200
                            or str(detail.url) != item.url
                            or len(detail.content) > 4_000_000
                        ):
                            item.raw_payload["public_house_detail_reason"] = "detail_unavailable"
                            continue
                        if _BLOCKED.search(detail.text[:2000]):
                            raise SourceFetchError(
                                f"{self.name}: provider challenge on detail page",
                                pages_fetched=1 + detail_checked,
                                items_seen=len(items),
                                partial_items=items,
                                halt_source=True,
                            )
                        evidence = verify_public_house_detail(
                            detail.text,
                            provider_name=self.name,
                            listing_id=item.source_listing_id,
                            price_eur=item.price_eur,
                            postal_code=item.postal_code,
                        )
                        item.raw_payload["public_house_detail_verified"] = evidence.verified
                        item.raw_payload["public_house_detail_reason"] = evidence.reason
                        if evidence.verified:
                            detail_verified += 1
                return SourceBatch(
                    items=items,
                    source_reported_count=None,
                    coverage_complete=False,
                    pages_fetched=1 + detail_checked,
                    next_cursor={
                        "country_code": "DE",
                        "frontier_cards_seen": seen,
                        "frontier_key": shard.key,
                        "detail_checked": detail_checked,
                        "detail_verified": detail_verified,
                        "detail_unchecked": max(0, len(items) - detail_checked),
                    },
                )
        except SourceFetchError:
            raise
        except (httpx.HTTPError, RuntimeError) as exc:
            raise SourceFetchError(
                f"{self.name}: public frontier unavailable ({type(exc).__name__})",
                pages_fetched=0, items_seen=0,
            ) from exc


class OhneMaklerGermanyPropertySource(PublicGermanHouseSource):
    portal = OHNE_MAKLER

    def frontier_paths(self) -> dict[str, str]:
        # Regional purchase-only URLs were checked as publicly accessible.
        # First pages can expose cheap houses missed by the national first page.
        return {
            "de-public-frontier": self.portal.search_path,
            "de-bayern": "/immobilien/haus-kaufen/bayern/",
            "de-baden-wurttemberg": "/immobilien/haus-kaufen/baden-wurttemberg/",
            "de-rheinland-pfalz": "/immobilien/haus-kaufen/rheinland-pfalz/",
            "de-nordrhein-westfalen": "/immobilien/haus-kaufen/nordrhein-westfalen/",
            "de-sachsen": "/immobilien/haus-kaufen/sachsen/",
            "de-sachsen-anhalt": "/immobilien/haus-kaufen/sachsen-anhalt/",
            "de-brandenburg": "/immobilien/haus-kaufen/brandenburg/",
            "de-mecklenburg-vorpommern": "/immobilien/haus-kaufen/mecklenburg-vorpommern/",
            "de-thuringen": "/immobilien/haus-kaufen/thuringen/",
        }


class ImmobilienDeGermanyPropertySource(PublicGermanHouseSource):
    portal = IMMOBILIEN_DE

    def frontier_paths(self) -> dict[str, str]:
        # These are public, independently confirmed buy-house landing pages.
        # Multiple regional first pages avoid relying exclusively on the
        # national site's expensive, popularity-ranked first page.
        return {
            "de-public-frontier": self.portal.search_path,
            "de-neubrandenburg": "/kaufen/haus/neubrandenburg/",
            "de-gangelt": "/kaufen/haus/gangelt/",
            "de-homburg": "/kaufen/haus/homburg/",
            "de-hagenow": "/kaufen/haus/hagenow/",
        }
