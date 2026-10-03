from decimal import Decimal

import httpx
import pytest

from app.sources.property.iad_de import IadGermanyPropertySource, parse_iad_search_page


def _page_html() -> str:
    return """
    <html><body>
      <div>928 Immobilien gefunden</div>
      <article>
        <div class="location">37247 Großalmerode</div>
        <div>Haus zu kaufen</div>
        <img srcset="https://img.iad.test/a-320.jpg 320w, https://img.iad.test/a-720.jpg 720w">
        <h2><a href="/immobilien/doppelhaushaelfte-in-grossalmerode-kauf-ks-mm0371">
          Doppelhaushälfte mit Garten und Ausbaupotenzial
        </a></h2>
        <div>Wohnfläche: ca. 105 m²</div>
        <div>Grundstücksfläche: ca. 530 m²</div>
        <div>Kaufpreis: 79.000 €</div>
      </article>
      <article>
        <div class="location">50667 Köln</div>
        <div>Haus zu kaufen</div>
        <h2><a href="/immobilien/stadthaus-in-koeln-kauf-nw-ab1234">
          Stadthaus in Köln
        </a></h2>
        <div>Wohnfläche: 140 m²</div>
        <div>Kaufpreis: 450.000 €</div>
      </article>
    </body></html>
    """


def test_parser_extracts_iad_object_id_location_areas_and_budget() -> None:
    page = parse_iad_search_page(
        _page_html(),
        page_url="https://iad-immobilien.de/immobilien/haeuser",
    )

    assert page.source_reported_count == 928
    assert page.cards_seen == page.cards_parsed == 2
    assert page.out_of_budget_cards == 1
    assert len(page.items) == 1

    item = page.items[0]
    assert item.source_listing_id == "KS-MM0371"
    assert item.url == (
        "https://iad-immobilien.de/immobilien/"
        "doppelhaushaelfte-in-grossalmerode-kauf-ks-mm0371"
    )
    assert item.title == "Doppelhaushälfte mit Garten und Ausbaupotenzial"
    assert item.postal_code == "37247"
    assert item.city == "Großalmerode"
    assert item.price_eur == Decimal(79000)
    assert item.living_area_m2 == Decimal(105)
    assert item.plot_area_m2 == Decimal(530)
    assert item.raw_payload["frontier_only"] is True
    assert item.raw_payload["thumbnail_url"] == "https://img.iad.test/a-720.jpg"


def test_iad_pagination_uses_public_ypage_parameter() -> None:
    source = IadGermanyPropertySource(frontier_pages=3)

    assert len(source.default_shards()) == 1
    assert source._page_url(1) == "https://iad-immobilien.de/immobilien/haeuser"
    assert source._page_url(2) == "https://iad-immobilien.de/immobilien/haeuser?__yPage=2"


@pytest.mark.asyncio
async def test_iad_frontier_never_claims_reconciliation_authority(monkeypatch) -> None:
    response = httpx.Response(
        200,
        text=_page_html(),
        request=httpx.Request("GET", "https://iad-immobilien.de/immobilien/haeuser"),
    )

    class Probe(IadGermanyPropertySource):
        async def _get(self, client, url):
            del client, url
            return response

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(
        "app.sources.property.iad_de.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )

    source = Probe(frontier_pages=1)
    batch = await source.fetch_shard(source.default_shards()[0], reconciliation=True)

    assert batch.coverage_complete is False
    assert batch.result_cap_hit is True
    assert batch.pages_fetched == 1
    assert len(batch.items) == 1
