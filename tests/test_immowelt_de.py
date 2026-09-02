from __future__ import annotations

from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from app.sources.property.immowelt_de import (
    ImmoweltGermanyPropertySource,
    parse_immowelt_search_page,
)


def _page_html(*, total: int = 1) -> str:
    return f"""
        <html><body>
          <h1>{total} Haus zum Kauf in Sachsen</h1>
          <div data-testid="serp-core-classified-card-testid">
            <a
              data-testid="card-mfe-covering-link-testid"
              href="https://www.immowelt.de/expose/6A365A1B-A119-423D-A29A-457B2FA19995?tracking=1"
              title="Einfamilienhaus zum Kauf - Dresden - 149.500 € - 4 Zimmer, 98,5 m², 377 m² Grundstück"
            ></a>
            <div>Frau Beispiel</div>
            <p>Eine lange Beschreibung, die WohnWerk nicht übernehmen darf.</p>
            <img
              src="https://images.example.test/house.jpg"
              alt="Einfamilienhaus zum Kauf 149.500 € 4 Zimmer 98,5 m² 377 m² Grundstück Dresden 01067"
            >
          </div>
          <button aria-label="zu seite 1">1</button>
        </body></html>
    """


def test_parser_keeps_only_minimal_public_facts_and_leading_zero_plz() -> None:
    page = parse_immowelt_search_page(
        _page_html(),
        page_url="https://www.immowelt.de/classified-search?page=1",
        region_key="sachsen",
        price_band_key="030000-149999",
    )

    assert page.source_reported_count == 1
    assert page.cards_seen == page.cards_parsed == 1
    item = page.items[0]
    assert item.source_listing_id == "6a365a1b-a119-423d-a29a-457b2fa19995"
    assert item.url == "https://www.immowelt.de/expose/6a365a1b-a119-423d-a29a-457b2fa19995"
    assert item.title == "Einfamilienhaus zum Kauf"
    assert item.price_eur == Decimal(149500)
    assert item.living_area_m2 == Decimal("98.5")
    assert item.plot_area_m2 == Decimal(377)
    assert item.postal_code == "01067"
    assert item.city == "Dresden"
    assert item.description is None
    assert "contact" not in item.raw_payload
    assert "image" not in item.raw_payload
    assert "Frau Beispiel" not in str(item.raw_payload)
    assert item.raw_payload["country_code"] == "DE"


def test_shards_cover_states_and_non_overlapping_budget_bands() -> None:
    source = ImmoweltGermanyPropertySource()
    shards = source.default_shards()

    assert len(shards) == 48
    assert len({shard.key for shard in shards}) == 48
    url = source._page_url("nordrhein-westfalen", "225000-300000", 2)
    query = parse_qs(urlparse(url).query)
    assert query["locations"] == ["AD04DE5"]
    assert query["priceMin"] == ["225000"]
    assert query["priceMax"] == ["300000"]
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
