from __future__ import annotations

from decimal import Decimal
from itertools import pairwise
from urllib.parse import parse_qs, urlparse

import pytest

from app.sources.property.germany import PROPERTY_PRICE_BANDS
from app.sources.property.immowelt_de import (
    ImmoweltGermanyPropertySource,
    parse_immowelt_search_page,
)


def _page_html(
    *,
    total: int = 1,
    title: str = (
        "Einfamilienhaus zum Kauf - Dresden - 89.500 € - "
        "4 Zimmer, 98,5 m², 377 m² Grundstück"
    ),
    href: str = (
        "https://www.immowelt.de/expose/"
        "6A365A1B-A119-423D-A29A-457B2FA19995?tracking=1"
    ),
) -> str:
    return f"""
        <html><body>
          <h1>{total} Haus zum Kauf in Sachsen</h1>
          <div data-testid="serp-core-classified-card-testid">
            <a
              data-testid="card-mfe-covering-link-testid"
              href="{href}"
              title="{title}"
            ></a>
            <div data-testid="cardmfe-description-box-address">Dresden 01067</div>
            <div>Frau Beispiel</div>
            <p>Eine lange Beschreibung, die WohnWerk nicht übernehmen darf.</p>
            <img
              src="https://images.example.test/house.jpg"
              alt="Einfamilienhaus zum Kauf 89.500 € 4 Zimmer 98,5 m² 377 m² Grundstück Dresden 01067"
            >
          </div>
          <button aria-label="zu seite 1">1</button>
        </body></html>
    """


def _with_blank_card_shell(html: str) -> str:
    return html.replace(
        '<button aria-label="zu seite 1">1</button>',
        (
            '<div data-testid="serp-core-classified-card-testid"></div>'
            '<button aria-label="zu seite 1">1</button>'
        ),
    )


def test_parser_keeps_only_minimal_public_facts_and_leading_zero_plz() -> None:
    page = parse_immowelt_search_page(
        _page_html(),
        page_url=(
            "https://www.immowelt.de/classified-search?"
            "distributionTypes=Buy&"
            "estateTypes=House&locations=AD04DE14&priceMax=149999&"
            "priceMin=30000&order=DateDesc&page=1"
        ),
        region_key="sachsen",
        price_band_key="030000-099999",
    )

    assert page.source_reported_count == 1
    assert page.cards_total == 1
    assert page.project_cards_skipped == 0
    assert page.blank_cards_skipped == 0
    assert page.cards_seen == page.cards_parsed == 1
    item = page.items[0]
    assert item.source_listing_id == "6a365a1b-a119-423d-a29a-457b2fa19995"
    assert item.url == "https://www.immowelt.de/expose/6a365a1b-a119-423d-a29a-457b2fa19995"
    assert item.title == "Einfamilienhaus zum Kauf"
    assert item.price_eur == Decimal(89500)
    assert item.living_area_m2 == Decimal("98.5")
    assert item.plot_area_m2 == Decimal(377)
    assert item.postal_code == "01067"
    assert item.city == "Dresden"
    assert item.description is None
    assert "contact" not in item.raw_payload
    assert "image" not in item.raw_payload
    assert "Frau Beispiel" not in str(item.raw_payload)
    assert item.raw_payload["format"] == "immowelt-public-search-v2"
    assert item.raw_payload["country_code"] == "DE"


def test_parser_accepts_observed_short_public_expose_identity() -> None:
    page = parse_immowelt_search_page(
        _page_html(
            href=(
                "https://www.immowelt.de/expose/26zklwh9fcdf?serp_view=list&"
                "search=distributionTypes%3DBuy#ln=classified_search_results"
            ),
            title=(
                "Reihenhaus zum Kauf - Cleebronn - 115.000 € - "
                "3 Zimmer, 88 m², 240 m² Grundstück"
            ),
        ),
        page_url="https://www.immowelt.de/classified-search",
        region_key="baden-wuerttemberg",
        price_band_key="100000-149999",
    )

    assert page.cards_seen == page.cards_parsed == 1
    assert page.blank_cards_skipped == 0
    item = page.items[0]
    assert item.source_listing_id == "26zklwh9fcdf"
    assert item.url == "https://www.immowelt.de/expose/26zklwh9fcdf"
    assert item.price_eur == Decimal(115000)
    assert item.living_area_m2 == Decimal(88)
    assert item.plot_area_m2 == Decimal(240)


def test_title_parser_handles_marketing_modifier_before_city() -> None:
    page = parse_immowelt_search_page(
        _page_html(
            title=(
                "Haus zum Kauf - Erstbezug - Bannewitz - 178.000 € - "
                "6 Zimmer, 180 m², 740 m² Grundstück"
            )
        ),
        page_url="https://www.immowelt.de/classified-search",
        region_key="sachsen",
        price_band_key="150000-200000",
    )

    item = page.items[0]
    assert item.title == "Haus zum Kauf - Erstbezug"
    assert item.city == "Bannewitz"
    assert item.price_eur == Decimal(178000)
    assert item.living_area_m2 == Decimal(180)
    assert item.plot_area_m2 == Decimal(740)


def test_project_card_without_variant_identity_is_skipped_explicitly() -> None:
    page = parse_immowelt_search_page(
        _page_html(
            href="https://www.immowelt.de/projekte/expose/k2rwa32?tracking=1",
            title=(
                "Reihenmittelhaus zum Kauf - Neubau - Nordost - 159.000 € - "
                "5 Zimmer, 120,1 m², 238 m² Grundstück"
            ),
        ),
        page_url="https://www.immowelt.de/classified-search",
        region_key="sachsen",
        price_band_key="150000-200000",
    )

    assert page.cards_total == 1
    assert page.project_cards_skipped == 1
    assert page.blank_cards_skipped == 0
    assert page.cards_seen == 0
    assert page.cards_parsed == 0
    assert page.items == []


def test_empty_card_shell_is_not_identity_bearing() -> None:
    page = parse_immowelt_search_page(
        _with_blank_card_shell(_page_html()),
        page_url="https://www.immowelt.de/classified-search",
        region_key="sachsen",
        price_band_key="030000-099999",
    )

    assert page.cards_total == 2
    assert page.blank_cards_skipped == 1
    assert page.cards_seen == page.cards_parsed == 1
    assert len(page.items) == 1


def test_current_page_size_drives_count_based_pagination() -> None:
    page = parse_immowelt_search_page(
        _page_html(total=81),
        page_url="https://www.immowelt.de/classified-search",
        region_key="sachsen",
        price_band_key="030000-099999",
    )

    assert page.max_page == 3


def test_price_bands_cover_exact_target_without_gaps_or_overlap() -> None:
    assert [
        (band.key, band.minimum_eur, band.maximum_eur)
        for band in PROPERTY_PRICE_BANDS
    ] == [
        ("030000-099999", 30_000, 99_999),
        ("100000-149999", 100_000, 149_999),
        ("150000-200000", 150_000, 200_000),
    ]
    for previous, current in pairwise(PROPERTY_PRICE_BANDS):
        assert previous.maximum_eur + 1 == current.minimum_eur


def test_explicit_auction_marker_is_retained_as_local_rejection_evidence() -> None:
    page = parse_immowelt_search_page(
        _page_html(
            title=(
                "Zwangsversteigerung Einfamilienhaus zum Kauf - Dresden - 120.000 € - "
                "4 Zimmer, 98,5 m², 377 m² Grundstück"
            )
        ),
        page_url="https://www.immowelt.de/classified-search?distributionTypes=Buy",
        region_key="sachsen",
        price_band_key="100000-149999",
    )

    item = page.items[0]
    assert item.raw_payload["source_distribution_type"] == "Buy"
    assert item.raw_payload["auction_detected"] is True
    assert "zwangsversteigerung" in item.raw_payload["auction_evidence"]


def test_shards_use_confirmed_classified_search_state() -> None:
    source = ImmoweltGermanyPropertySource()
    shards = source.default_shards()

    assert len(shards) == 48
    assert len({shard.key for shard in shards}) == 48

    url = source._page_url("nordrhein-westfalen", "150000-200000", 2)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.path == "/classified-search"
    assert query["distributionTypes"] == ["Buy"]
    assert query["estateTypes"] == ["House"]
    assert query["locations"] == ["AD04DE5"]
    assert query["priceMin"] == ["150000"]
    assert query["priceMax"] == ["200000"]
    assert query["order"] == ["DateDesc"]
    assert query["page"] == ["2"]


@pytest.mark.asyncio
async def test_single_page_reconciliation_is_authoritative_without_browser() -> None:
    class ProbeSource(ImmoweltGermanyPropertySource):
        async def _load_html(self, url: str) -> tuple[str, str]:
            return _page_html(), url

    source = ProbeSource(request_delay_seconds=1.0)
    shard = next(shard for shard in source.default_shards() if shard.key.startswith("sachsen:"))
    batch = await source.fetch_shard(shard, reconciliation=True)

    assert batch.coverage_complete is True
    assert batch.result_cap_hit is False
    assert batch.pages_fetched == 1
    assert batch.next_cursor["discovery_count_delta"] == 0
    assert batch.next_cursor["discovery_cards_total"] == 1
    assert batch.next_cursor["discovery_project_cards_skipped"] == 0
    assert batch.next_cursor["discovery_blank_cards_skipped"] == 0


@pytest.mark.asyncio
async def test_project_card_blocks_reconciliation_authority() -> None:
    class ProbeSource(ImmoweltGermanyPropertySource):
        async def _load_html(self, url: str) -> tuple[str, str]:
            return (
                _page_html(
                    href="https://www.immowelt.de/projekte/expose/k2rwa32",
                    title=(
                        "Reihenmittelhaus zum Kauf - Neubau - Nordost - 159.000 € - "
                        "5 Zimmer, 120,1 m², 238 m² Grundstück"
                    ),
                ),
                url,
            )

    source = ProbeSource(request_delay_seconds=1.0)
    shard = next(shard for shard in source.default_shards() if shard.key.startswith("sachsen:"))
    batch = await source.fetch_shard(shard, reconciliation=True)

    assert batch.coverage_complete is False
    assert batch.next_cursor["discovery_project_cards_skipped"] == 1


@pytest.mark.asyncio
async def test_blank_card_shell_blocks_reconciliation_authority() -> None:
    class ProbeSource(ImmoweltGermanyPropertySource):
        async def _load_html(self, url: str) -> tuple[str, str]:
            return _with_blank_card_shell(_page_html()), url

    source = ProbeSource(request_delay_seconds=1.0)
    shard = next(shard for shard in source.default_shards() if shard.key.startswith("sachsen:"))
    batch = await source.fetch_shard(shard, reconciliation=True)

    assert batch.coverage_complete is False
    assert batch.next_cursor["discovery_blank_cards_skipped"] == 1
    assert batch.next_cursor["discovery_cards_seen"] == 1
    assert batch.next_cursor["discovery_cards_parsed"] == 1
