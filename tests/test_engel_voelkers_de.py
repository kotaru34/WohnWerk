from decimal import Decimal

import httpx
import pytest

from app.sources.property.engel_voelkers_de import (
    EngelVoelkersGermanyPropertySource,
    _english_decimal,
    parse_engel_voelkers_search_page,
)


def _page_html() -> str:
    return """
    <html><body>
      <h1>Houses for sale in Germany – 3,765 results</h1>
      <script type="application/ld+json" id="structured-buyer-data-jsonld">
        {
          "@type": "ItemList",
          "itemListElement": [
            {
              "@type": "ListItem",
              "url": "https://www.engelvoelkers.com/de/en/exposes/95abd015-01a0-583e-a0e2-22cca215dec5",
              "image": "https://uploadcare.engelvoelkers.com/source-backed-preview/"
            }
          ]
        }
      </script>
      <div class="property-card">
        <div>Add to favorites</div>
        <picture>
          <source srcset="https://images.ev.test/house-320.webp 320w, https://images.ev.test/house-720.webp 720w, https://images.ev.test/house-1400.webp 1400w">
          <img src="https://images.ev.test/house-320.webp" alt="Wohlfühlhaus">
        </picture>
        <div>Althausen, Münnerstadt, Bavaria, Germany</div>
        <h2>
          <a href="/de/en/exposes/95abd015-01a0-583e-a0e2-22cca215dec5">
            Wohlfühlhaus mit Einliegerwohnung und moderner Energieversorgung
          </a>
        </h2>
        <div>€149,000</div>
        <ul>
          <li>5 Rooms</li>
          <li>~131 m² Living area</li>
          <li>~344 m² Plot surface</li>
        </ul>
      </div>
      <div class="property-card">
        <div>Krumbach, Fürth, Hessen, Germany</div>
        <h2>
          <a href="/de/en/exposes/11111111-2222-3333-4444-555555555555">
            Charmantes Einfamilienhaus in ruhiger Feldrandlage
          </a>
        </h2>
        <div>€549,000</div>
        <div>~210 m² Living area</div>
        <div>~862 m² Plot surface</div>
      </div>
      <div class="property-card">
        <div>Seelbach, Siegen, North Rhine-Westphalia, Germany</div>
        <h2>
          <a href="/de/en/exposes/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee">
            VERKAUFT! Familienfreundliches Wohnhaus in bevorzugter Lage
          </a>
        </h2>
        <div>€125,000</div>
        <div>~158 m² Living area</div>
        <div>~489 m² Plot surface</div>
      </div>
      <div class="property-card">
        <div>Memmingen, Bavaria, Germany</div>
        <h2>
          <a href="/de/en/exposes/8689ddd0-adb5-563c-9844-328132c4144b">
            Exklusives Anwesen in Memmingen
          </a>
        </h2>
        <div>Price on request</div>
        <div>~350 m² Living area</div>
        <div>~1200 m² Plot surface</div>
      </div>
    </body></html>
    """


def test_parser_extracts_budget_house_and_skips_unavailable_and_expensive() -> None:
    page = parse_engel_voelkers_search_page(
        _page_html(),
        page_url="https://www.engelvoelkers.com/de/en/properties/res/sale/house",
    )

    assert page.source_reported_count == 3765
    assert page.cards_seen == page.cards_parsed == 4
    assert page.unavailable_cards == 1
    assert page.price_unknown_cards == 1
    assert page.out_of_budget_cards == 1
    assert len(page.items) == 1

    item = page.items[0]
    assert item.source_listing_id == "95abd015-01a0-583e-a0e2-22cca215dec5"
    assert item.url == (
        "https://www.engelvoelkers.com/de/en/exposes/"
        "95abd015-01a0-583e-a0e2-22cca215dec5"
    )
    assert item.title == "Wohlfühlhaus mit Einliegerwohnung und moderner Energieversorgung"
    assert item.city == "Münnerstadt"
    assert item.postal_code is None
    assert item.price_eur == Decimal(149000)
    assert item.living_area_m2 == Decimal(131)
    assert item.plot_area_m2 == Decimal(344)
    assert item.raw_payload["country_code"] == "DE"
    assert item.raw_payload["frontier_only"] is True
    assert item.raw_payload["source_location"] == (
        "Althausen, Münnerstadt, Bavaria, Germany"
    )
    assert item.raw_payload["thumbnail_url"] == (
        "https://uploadcare.engelvoelkers.com/source-backed-preview/"
    )
    assert item.raw_payload["thumbnail_semantics"] == "source_search_card"


def test_pagination_is_newest_first_and_source_is_single_frontier() -> None:
    source = EngelVoelkersGermanyPropertySource(frontier_pages=3)

    assert len(source.default_shards()) == 1
    assert source._page_url(1) == (
        "https://www.engelvoelkers.com/de/en/properties/res/sale/house"
        "?sorting=publishedAt"
    )
    assert source._page_url(2) == (
        "https://www.engelvoelkers.com/de/en/properties/res/sale/house"
        "?page=2&sorting=publishedAt"
    )


@pytest.mark.asyncio
async def test_frontier_never_claims_reconciliation_authority(monkeypatch) -> None:
    response = httpx.Response(
        200,
        text=_page_html(),
        request=httpx.Request(
            "GET",
            "https://www.engelvoelkers.com/de/en/properties/res/sale/house",
        ),
    )

    class Probe(EngelVoelkersGermanyPropertySource):
        async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
            del client, url
            return response

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(
        "app.sources.property.engel_voelkers_de.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )

    source = Probe(frontier_pages=1)
    batch = await source.fetch_shard(source.default_shards()[0], reconciliation=True)

    assert batch.coverage_complete is False
    assert batch.result_cap_hit is True
    assert batch.pages_fetched == 1
    assert len(batch.items) == 1



def test_english_number_parser_treats_comma_as_thousands_separator() -> None:
    assert _english_decimal("149,000") == Decimal(149000)
    assert _english_decimal("1,432.5") == Decimal("1432.5")
