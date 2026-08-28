from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx

from app.sources.base import RawProperty, SourceBatch, SourceFetchError, SourceShardSpec
from app.sources.property.immmo import (
    LOCATION_AREA_RE,
    PAGE_SIZE,
    PRICE_RE,
    _canonical_external_url,
    _clean_text,
    _decimal,
    _source_id,
)
from app.sources.property.immmo_v2 import (
    RESULT_HEADING_RE,
    ImmmoPage,
    _AnchorOccurrence,
    _is_title_text,
    _pagination_state,
    _VisibleStreamParser,
)
from app.sources.property.immmo_v2 import ImmmoPropertySource as _ImmmoPropertySourceV2

AREA_NUMBER_PATTERN = r"([\d.]+(?:,\d+)?)"
AREA_PREFIX_PATTERN = r"(?:ca\.?\s*|rund\s+|knapp\s+)?"
AREA_UNIT_PATTERN = r"\s*m(?:²|2)\b"
LIVING_AREA_LABEL_PATTERN = r"(?:Wohnfläche|Wohn[\s/-]*Nutzfläche)"
PLOT_AREA_LABEL_PATTERN = r"(?:Grundstücksfläche|Grundstück|Grund)"

LIVING_AREA_PATTERNS = (
    re.compile(
        rf"\b{LIVING_AREA_LABEL_PATTERN}\b\s*(?:von|:)?\s*"
        rf"{AREA_PREFIX_PATTERN}{AREA_NUMBER_PATTERN}{AREA_UNIT_PATTERN}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"{AREA_PREFIX_PATTERN}{AREA_NUMBER_PATTERN}{AREA_UNIT_PATTERN}\s+"
        rf"(?:gewichtete\s+)?{LIVING_AREA_LABEL_PATTERN}\b(?!\s*:)",
        re.IGNORECASE,
    ),
)
USABLE_AREA_PATTERNS = (
    re.compile(
        rf"\bNutzfläche\b\s*(?:von|:)?\s*"
        rf"{AREA_PREFIX_PATTERN}{AREA_NUMBER_PATTERN}{AREA_UNIT_PATTERN}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"{AREA_PREFIX_PATTERN}{AREA_NUMBER_PATTERN}{AREA_UNIT_PATTERN}\s+"
        rf"Nutzfläche\b(?!\s*:)",
        re.IGNORECASE,
    ),
)

# Flattened IMMMO card text can look like
# ``Nutzfläche: 120 m² Grundstücksfläche: 784 m²``. A naive value-before-label
# regex would incorrectly bind 120 to Grundstücksfläche. Prefer label-before-value
# evidence and only accept value-before-label forms when the following label does not
# start a new ``label: value`` metadata field.
PLOT_AREA_LABEL_FIRST_PATTERNS = (
    re.compile(
        rf"\b(?:Grundstücksfläche|Grundstück)\b\s*(?:von|:)?\s*"
        rf"{AREA_PREFIX_PATTERN}{AREA_NUMBER_PATTERN}{AREA_UNIT_PATTERN}",
        re.IGNORECASE,
    ),
)
PLOT_AREA_VALUE_FIRST_PATTERNS = (
    re.compile(
        rf"{AREA_PREFIX_PATTERN}{AREA_NUMBER_PATTERN}{AREA_UNIT_PATTERN}\s+"
        rf"(?:groß(?:en|es|e)?\s+)?{PLOT_AREA_LABEL_PATTERN}\b(?!\s*:)",
        re.IGNORECASE,
    ),
)


def _anchor_matches_title(anchor_text: str, expected_title: str) -> bool:
    if not _is_title_text(anchor_text):
        return False
    anchor = _clean_text(anchor_text).casefold()
    expected = _clean_text(expected_title).casefold()
    if len(expected) < 8:
        return False
    if expected in anchor:
        return True
    if not expected.startswith(anchor):
        return False
    # Provider cards often shorten the clickable title while the surrounding visible
    # card contains a longer title. Accept that relation only when the anchor still carries
    # substantial title text; this keeps generic/foreign anchors from becoming identity.
    return len(anchor) >= 12 and len(anchor) >= max(12, int(len(expected) * 0.35))


def _choose_card_anchor(
    anchors: list[_AnchorOccurrence],
    *,
    heading_start: int,
    heading_end: int,
    segment_end: int,
    page_url: str,
    expected_title: str,
) -> tuple[_AnchorOccurrence, str] | None:
    """Return a card link only when its visible text belongs to this exact card.

    IMMMO pages can contain unrelated external anchors inside the visible segment. A blind
    first-link fallback can therefore bind one property's title/price to another property's
    URL. Prefer losing the external URL and using our synthetic fallback identity over
    creating a false cross-card association.
    """
    wrapping: list[tuple[_AnchorOccurrence, str]] = []
    following: list[tuple[_AnchorOccurrence, str]] = []

    for anchor in anchors:
        if anchor.start >= segment_end:
            break
        if anchor.end <= heading_start:
            continue

        original_url = _canonical_external_url(anchor.href, page_url=page_url)
        if not original_url:
            continue

        if anchor.start <= heading_start and anchor.end >= heading_end and anchor.end <= segment_end:
            wrapping.append((anchor, original_url))
        elif anchor.start >= heading_end and anchor.start < segment_end:
            following.append((anchor, original_url))

    for candidates in (wrapping, following):
        for anchor, original_url in candidates:
            if _anchor_matches_title(anchor.text, expected_title):
                return anchor, original_url
    return None


def _fallback_title(card_text: str, heading_text: str) -> str:
    body = _clean_text(card_text)
    heading = _clean_text(heading_text)
    if body.startswith(heading):
        body = body[len(heading) :].strip()

    boundaries: list[int] = []
    price = PRICE_RE.search(body)
    if price is not None:
        boundaries.append(price.start())
    facts = LOCATION_AREA_RE.search(body)
    if facts is not None:
        boundaries.append(facts.start())

    if boundaries:
        body = body[: min(boundaries)]
    candidate = _clean_text(body).strip(" -–")
    return candidate[:500] or heading[:500]


def _explicit_living_area(text: str) -> Decimal | None:
    for pattern in LIVING_AREA_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            return _decimal(match.group(1))
    return None


def _explicit_usable_area(text: str) -> Decimal | None:
    for pattern in USABLE_AREA_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            return _decimal(match.group(1))
    return None


def _explicit_plot_area(text: str) -> Decimal | None:
    for patterns in (PLOT_AREA_LABEL_FIRST_PATTERNS, PLOT_AREA_VALUE_FIRST_PATTERNS):
        for pattern in patterns:
            match = pattern.search(text)
            if match is not None:
                return _decimal(match.group(1))
    return None


def _areas_close(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return False
    tolerance = max(Decimal(1), max(abs(left), abs(right)) * Decimal("0.01"))
    return abs(left - right) <= tolerance


def _display_area_semantics(
    *,
    display_area: Decimal | None,
    explicit_living_area: Decimal | None,
    explicit_plot_area: Decimal | None,
) -> str:
    """Describe what IMMMO's unlabeled card-level area appears to represent."""
    if explicit_living_area is not None:
        if _areas_close(display_area, explicit_living_area):
            return "living_explicit_primary"
        if _areas_close(display_area, explicit_plot_area):
            return "living_explicit_display_plot"
        return "living_explicit_nonprimary"
    if _areas_close(display_area, explicit_plot_area):
        return "plot_explicit_primary"
    return "unknown"


def _summary_price(card_text: str, facts: re.Match[str] | None) -> Decimal | None:
    """Accept only the dedicated search-card price before the PLZ/area facts row.

    IMMMO flattens downstream descriptions into the same visible card segment. Those
    descriptions may contain unrelated monetary values such as annual rental income,
    provision or running costs. If the card itself says ``Preis auf Anfrage`` there is no
    numeric purchase price before the structured PLZ/area row, so all later euro amounts
    must remain descriptive text rather than becoming ``price_eur``.
    """
    if facts is None:
        return None
    summary = card_text[: facts.start()]
    price_match = PRICE_RE.search(summary)
    return _decimal(price_match.group(1)) if price_match else None


def _synthetic_identity(
    *,
    postal_code: str,
    city: str | None,
    display_area: object | None,
    price: object | None,
    title: str,
) -> tuple[str, str]:
    # Keep the legacy card-level area in the fallback fingerprint. Its semantics may be
    # unknown, but changing this to semantic Wohnfläche would itself create identity churn.
    key = "|".join(
        (
            postal_code,
            city or "",
            str(display_area or ""),
            str(price or ""),
            title.casefold(),
        )
    )
    fingerprint = _source_id(f"immmo-fallback|{key}")
    return fingerprint, f"https://www.immmo.at/immo/wohnwerk-fallback/{fingerprint}"


def parse_immmo_search_page(html: str, *, page_url: str) -> ImmmoPage:
    parser = _VisibleStreamParser()
    parser.feed(html)
    page_text = parser.text

    count_match = re.search(
        r"\d+\s+bis\s+\d+\s+von\s+(?P<lower>mehr\s+als\s+)?(?P<count>[\d.]+)",
        page_text,
        re.IGNORECASE,
    )
    reported_count = None
    count_is_lower_bound = False
    if count_match:
        reported_count = int(count_match.group("count").replace(".", ""))
        count_is_lower_bound = bool(count_match.group("lower"))

    result_headings = []
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
        card_text = page_text[segment_start:segment_end]
        heading_postal_code = heading_match.group("plz")
        facts = LOCATION_AREA_RE.search(card_text)
        if facts is not None and facts.group("plz") != heading_postal_code:
            facts = None
        if facts is not None:
            postal_code = facts.group("plz")
            city = _clean_text(facts.group("city")).strip(" ,")
            display_area = _decimal(facts.group("area"))
        else:
            postal_code = heading_postal_code
            city = _clean_text(heading_match.group("city")).strip(" ,") or None
            display_area = None

        explicit_living_area = _explicit_living_area(card_text)
        explicit_usable_area = _explicit_usable_area(card_text)
        # Combined labels such as Wohn-/Nutzfläche are living evidence first. Do not
        # duplicate the same number as a separate generic Nutzfläche.
        if _areas_close(explicit_usable_area, explicit_living_area):
            explicit_usable_area = None
        explicit_plot_area = _explicit_plot_area(card_text)
        area_semantics = _display_area_semantics(
            display_area=display_area,
            explicit_living_area=explicit_living_area,
            explicit_plot_area=explicit_plot_area,
        )

        title = _fallback_title(card_text, heading.text)
        price = _summary_price(card_text, facts)
        chosen = _choose_card_anchor(
            anchors,
            heading_start=heading.start,
            heading_end=heading.end,
            segment_end=segment_end,
            page_url=page_url,
            expected_title=title,
        )

        original_url_missing = chosen is None
        if chosen is not None:
            _anchor, listing_url = chosen
            source_listing_id = _source_id(listing_url)
            original_host: str | None = (urlparse(listing_url).hostname or "").casefold()
        else:
            source_listing_id, listing_url = _synthetic_identity(
                postal_code=postal_code,
                city=city,
                display_area=display_area,
                price=price,
                title=title,
            )
            original_host = None

        cards_parsed += 1
        items_by_url[listing_url] = RawProperty(
            source_listing_id=source_listing_id,
            url=listing_url,
            title=title[:500],
            description=None,
            price_eur=price,
            living_area_m2=explicit_living_area,
            plot_area_m2=explicit_plot_area,
            postal_code=postal_code,
            city=city,
            raw_payload={
                "format": "immmo-search-discovery-v12",
                "original_host": original_host,
                "original_url_missing": original_url_missing,
                "identity_stable": not original_url_missing,
                "discovery_url": page_url,
                "source_postal_code": postal_code,
                "source_heading_kind": _clean_text(heading_match.group("kind")),
                "price_semantics": "summary_numeric" if price is not None else "unknown",
                "source_price_eur": str(price) if price is not None else None,
                "display_area_m2": str(display_area) if display_area is not None else None,
                "display_area_semantics": area_semantics,
                "explicit_living_area_m2": (
                    str(explicit_living_area) if explicit_living_area is not None else None
                ),
                "explicit_usable_area_m2": (
                    str(explicit_usable_area) if explicit_usable_area is not None else None
                ),
                "explicit_plot_area_m2": (
                    str(explicit_plot_area) if explicit_plot_area is not None else None
                ),
            },
        )

    current_page, pagination_max_page = _pagination_state(
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
    )


def _page_target(reported_count: int) -> int:
    return max(1, math.ceil(reported_count / PAGE_SIZE))


def _validate_page_quality(
    page: ImmmoPage,
    *,
    shard_key: str,
    page_number: int,
    target_pages: int,
) -> None:
    if page.cards_seen == 0:
        raise RuntimeError(
            f"IMMMO returned no result cards for shard {shard_key!r} page {page_number}"
        )
    if page.cards_parsed != page.cards_seen:
        raise RuntimeError(
            f"IMMMO card materialization incomplete for shard {shard_key!r} page {page_number}: "
            f"parsed {page.cards_parsed}/{page.cards_seen} visible cards"
        )
    if page_number < target_pages and page.cards_seen < math.ceil(PAGE_SIZE * 0.75):
        raise RuntimeError(
            f"IMMMO non-terminal page unexpectedly short for shard {shard_key!r} "
            f"page {page_number}: saw {page.cards_seen} cards"
        )
    if not page.items:
        raise RuntimeError(
            f"IMMMO returned no materialized listings for shard {shard_key!r} page {page_number}"
        )

    with_plz = sum(item.postal_code is not None for item in page.items)
    if with_plz / len(page.items) < 0.90:
        raise RuntimeError(
            f"IMMMO location quality too low for shard {shard_key!r} page {page_number}: "
            f"PLZ {with_plz}/{len(page.items)}"
        )


class ImmmoPropertySource(_ImmmoPropertySourceV2):
    """IMMMO adapter with count-driven traversal and lossless card discovery."""

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        del cursor
        base_url = str(shard.params.get("search_url") or "")
        if not base_url:
            raise ValueError(f"Invalid IMMMO shard URL: {base_url!r}")

        headers = {
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian property search)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
        }
        items_by_id: dict[str, RawProperty] = {}
        initial_reported_count: int | None = None
        latest_reported_count: int | None = None
        max_reported_count = 0
        count_is_lower_bound = False
        pages_fetched = 0
        cards_seen = 0
        cards_parsed = 0
        synthetic_cards = 0
        result_cap_hit = False
        target_pages = 1
        page_number = 1
        failed_page_number: int | None = None
        failed_page_cards_seen: int | None = None
        failed_page_cards_parsed: int | None = None

        def progress_cursor() -> dict[str, Any]:
            return {
                "newest_ids": list(items_by_id)[:100],
                "discovery_cards_seen": cards_seen,
                "discovery_cards_parsed": cards_parsed,
                "discovery_synthetic_cards": synthetic_cards,
                "discovery_initial_reported": initial_reported_count,
                "discovery_latest_reported": latest_reported_count,
                "discovery_max_reported": max_reported_count or None,
                "discovery_target_pages": target_pages,
                "discovery_failed_page": failed_page_number,
                "discovery_failed_page_cards_seen": failed_page_cards_seen,
                "discovery_failed_page_cards_parsed": failed_page_cards_parsed,
            }

        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=self.timeout_seconds,
                follow_redirects=True,
            ) as client:
                while page_number <= target_pages:
                    if page_number > 1:
                        await self._sleep()
                    response = await self._get(client, self._page_url(base_url, page_number))
                    page = parse_immmo_search_page(response.text, page_url=str(response.url))
                    if page.reported_count is None:
                        raise RuntimeError(
                            f"IMMMO result count missing for shard {shard.key!r} page {page_number}"
                        )

                    latest_reported_count = page.reported_count
                    if initial_reported_count is None:
                        initial_reported_count = page.reported_count
                    max_reported_count = max(max_reported_count, page.reported_count)
                    count_is_lower_bound = count_is_lower_bound or page.count_is_lower_bound
                    target_pages = max(page_number, _page_target(latest_reported_count))
                    max_target_pages = _page_target(max_reported_count)

                    if count_is_lower_bound or max_target_pages > self.hard_max_pages_per_shard:
                        result_cap_hit = True
                    target_pages = min(target_pages, self.hard_max_pages_per_shard)

                    failed_page_number = page_number
                    failed_page_cards_seen = page.cards_seen
                    failed_page_cards_parsed = page.cards_parsed
                    _validate_page_quality(
                        page,
                        shard_key=shard.key,
                        page_number=page_number,
                        target_pages=target_pages,
                    )
                    failed_page_number = None
                    failed_page_cards_seen = None
                    failed_page_cards_parsed = None

                    items_by_id.update({item.source_listing_id: item for item in page.items})
                    pages_fetched += 1
                    cards_seen += page.cards_seen
                    cards_parsed += page.cards_parsed
                    synthetic_cards += sum(
                        bool(item.raw_payload.get("original_url_missing")) for item in page.items
                    )

                    if not reconciliation and page_number >= self.incremental_pages:
                        break
                    if result_cap_hit and page_number >= self.hard_max_pages_per_shard:
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
                partial_items=list(items_by_id.values()),
            ) from exc

        benchmark_count = latest_reported_count or initial_reported_count or 0
        count_tolerance = max(PAGE_SIZE * 2, math.ceil(benchmark_count * 0.01))
        count_delta = cards_seen - benchmark_count
        count_plausible = benchmark_count > 0 and abs(count_delta) <= count_tolerance
        synthetic_tolerance = max(3, math.ceil(cards_seen * 0.05))
        link_quality_plausible = synthetic_cards <= synthetic_tolerance
        traversal_complete = pages_fetched >= target_pages
        coverage_complete = (
            reconciliation
            and traversal_complete
            and not result_cap_hit
            and cards_seen == cards_parsed
            and count_plausible
            and link_quality_plausible
        )

        cursor_out = progress_cursor()
        cursor_out["discovery_traversal_complete"] = traversal_complete
        cursor_out["discovery_count_delta"] = count_delta
        cursor_out["discovery_count_tolerance"] = count_tolerance
        cursor_out["discovery_synthetic_tolerance"] = synthetic_tolerance
        cursor_out["discovery_link_quality_ok"] = link_quality_plausible
        return SourceBatch(
            items=list(items_by_id.values()),
            next_cursor=cursor_out,
            source_reported_count=initial_reported_count,
            coverage_complete=coverage_complete,
            result_cap_hit=result_cap_hit,
            pages_fetched=pages_fetched,
        )