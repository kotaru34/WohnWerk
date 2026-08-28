from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.property_acquisition import filter_property_items_by_budget
from app.sources.base import RawProperty, SourceBatch, SourceShardSpec
from app.sources.property import sreal as _base
from app.sources.property.immmo import _clean_text, _decimal

BASE_URL = _base.BASE_URL
SEARCH_URL = _base.SEARCH_URL


@dataclass(frozen=True, slots=True)
class SRealPage:
    items: list[RawProperty]
    max_page: int
    cards_seen: int
    cards_parsed: int
    raw_detail_anchors: int
    duplicate_detail_anchors: int
    metadata_fallbacks: int


def _fallback_card_metadata(
    texts: list[str],
    *,
    listing_id: str,
) -> tuple[str, str | None, str | None]:
    """Materialize a known detail URL even when card metadata is sparse.

    Discovery identity comes from the provider-issued detail ID. Search-card area/price
    fields are enrichment, not a prerequisite for knowing that the property exists.
    """
    text = max((_clean_text(value) for value in texts), key=len, default="")
    if not text:
        return f"s REAL Immobilie {listing_id}", None, None

    boundaries: list[int] = []
    area = _base.AREA_RE.search(text)
    price = _base.PRICE_RE.search(text)
    if area is not None:
        boundaries.append(area.start())
    if price is not None:
        boundaries.append(price.start())
    prefix = _clean_text(text[: min(boundaries)] if boundaries else text)

    locations = list(_base.PLZ_RE.finditer(prefix))
    if not locations:
        return prefix[:500] or f"s REAL Immobilie {listing_id}", None, None

    location = locations[-1]
    title = _clean_text(prefix[: location.start()]).rstrip(" -–")
    city = _clean_text(prefix[location.end() :]).strip(" ,")
    return (
        title[:500] or f"s REAL Immobilie {listing_id}",
        location.group("plz"),
        city or None,
    )


def parse_sreal_search_page(html: str, *, page_url: str) -> SRealPage:
    """Parse one s REAL result page by unique provider-issued listing ID.

    A result card may contain multiple anchors to the same detail page (for example an
    image link and a text link). Those are one property, not multiple visible cards.
    """
    parser = _base._AnchorParser()
    parser.feed(html)

    grouped: dict[str, tuple[str, list[_base._Anchor]]] = {}
    raw_detail_anchors = 0
    for anchor in parser.anchors:
        detail = _base._canonical_detail_url(anchor.href, page_url=page_url)
        if detail is None:
            continue
        raw_detail_anchors += 1
        url, listing_id = detail
        if listing_id not in grouped:
            grouped[listing_id] = (url, [])
        grouped[listing_id][1].append(anchor)

    items: list[RawProperty] = []
    metadata_fallbacks = 0
    for listing_id, (url, anchors) in grouped.items():
        candidates = sorted(anchors, key=lambda anchor: len(anchor.text), reverse=True)
        facts = None
        for anchor in candidates:
            facts = _base._parse_card_facts(anchor.text)
            if facts is not None:
                break

        if facts is not None:
            area = _decimal(facts.area)
            area_kind = facts.area_kind.casefold()
            price = _decimal(facts.price)
            title = facts.title[:500]
            postal_code = facts.postal_code
            city = facts.city
            living_area = area if area_kind == "wohnfläche" else None
            plot_area = area if area_kind == "grundfläche" else None
            metadata_complete = True
        else:
            metadata_fallbacks += 1
            title, postal_code, city = _fallback_card_metadata(
                [anchor.text for anchor in candidates],
                listing_id=listing_id,
            )
            price = None
            living_area = None
            plot_area = None
            metadata_complete = False

        items.append(
            RawProperty(
                source_listing_id=listing_id,
                url=url,
                title=title,
                description=None,
                price_eur=price,
                living_area_m2=living_area,
                plot_area_m2=plot_area,
                postal_code=postal_code,
                city=city,
                raw_payload={
                    "format": "sreal-search-discovery-v3",
                    "discovery_url": page_url,
                    "source_postal_code": postal_code,
                    "identity_stable": True,
                    "search_metadata_complete": metadata_complete,
                    "search_anchor_count": len(anchors),
                },
            )
        )

    cards_seen = len(grouped)
    cards_parsed = len(items)
    return SRealPage(
        items=items,
        max_page=_base._max_page(parser.anchors),
        cards_seen=cards_seen,
        cards_parsed=cards_parsed,
        raw_detail_anchors=raw_detail_anchors,
        duplicate_detail_anchors=max(0, raw_detail_anchors - cards_seen),
        metadata_fallbacks=metadata_fallbacks,
    )


class SRealPropertySource(_base.SRealPropertySource):
    """s REAL adapter with listing-ID-driven discovery accounting."""

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
        raw_detail_anchors = 0
        duplicate_detail_anchors = 0
        metadata_fallbacks = 0
        detail_attempted = 0
        detail_succeeded = 0
        detail_failed = 0
        budget_accepted = 0
        budget_price_unknown = 0
        budget_price_below_min = 0
        budget_price_above_max = 0
        result_cap_hit = False

        def budget_filter(items: list[RawProperty]) -> list[RawProperty]:
            nonlocal budget_accepted
            nonlocal budget_price_unknown
            nonlocal budget_price_below_min
            nonlocal budget_price_above_max
            accepted, counts = filter_property_items_by_budget(items)
            budget_accepted += counts["accepted"]
            budget_price_unknown += counts["price_unknown"]
            budget_price_below_min += counts["price_below_min"]
            budget_price_above_max += counts["price_above_max"]
            return accepted

        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            first_response = await self._get(client, self._page_url(base_url, 1))
            first = parse_sreal_search_page(first_response.text, page_url=str(first_response.url))
            _base._validate_page(first, page_number=1, expected_minimum=0)

            page_size = first.cards_seen
            max_page = first.max_page
            if max_page > self.hard_max_pages:
                result_cap_hit = True
            target_pages = min(
                max_page,
                self.hard_max_pages,
                max_page if reconciliation else self.incremental_pages,
            )

            first_candidates = budget_filter(first.items)
            first_items, attempted, succeeded, failed = await self._enrich_page_items(
                client, first_candidates
            )
            detail_attempted += attempted
            detail_succeeded += succeeded
            detail_failed += failed
            items_by_id.update({item.source_listing_id: item for item in first_items})
            pages_fetched = 1
            cards_seen = first.cards_seen
            cards_parsed = first.cards_parsed
            raw_detail_anchors = first.raw_detail_anchors
            duplicate_detail_anchors = first.duplicate_detail_anchors
            metadata_fallbacks = first.metadata_fallbacks

            for page_number in range(2, target_pages + 1):
                await self._sleep()
                response = await self._get(client, self._page_url(base_url, page_number))
                page = parse_sreal_search_page(response.text, page_url=str(response.url))
                minimum = 0 if page_number == max_page else max(1, int(page_size * 0.75))
                _base._validate_page(page, page_number=page_number, expected_minimum=minimum)
                page_candidates = budget_filter(page.items)
                page_items, attempted, succeeded, failed = await self._enrich_page_items(
                    client, page_candidates
                )
                detail_attempted += attempted
                detail_succeeded += succeeded
                detail_failed += failed
                items_by_id.update({item.source_listing_id: item for item in page_items})
                pages_fetched += 1
                cards_seen += page.cards_seen
                cards_parsed += page.cards_parsed
                raw_detail_anchors += page.raw_detail_anchors
                duplicate_detail_anchors += page.duplicate_detail_anchors
                metadata_fallbacks += page.metadata_fallbacks

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
                "discovery_raw_detail_anchors": raw_detail_anchors,
                "discovery_duplicate_detail_anchors": duplicate_detail_anchors,
                "discovery_metadata_fallbacks": metadata_fallbacks,
                "discovery_max_page": max_page,
                "acquisition_budget_accepted": budget_accepted,
                "acquisition_budget_price_unknown": budget_price_unknown,
                "acquisition_budget_price_below_min": budget_price_below_min,
                "acquisition_budget_price_above_max": budget_price_above_max,
                "detail_enrichment_attempted": detail_attempted,
                "detail_enrichment_succeeded": detail_succeeded,
                "detail_enrichment_failed": detail_failed,
            },
            source_reported_count=None,
            coverage_complete=coverage_complete,
            result_cap_hit=result_cap_hit,
            pages_fetched=pages_fetched,
        )
