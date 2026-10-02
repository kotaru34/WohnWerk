from decimal import Decimal

import httpx
import pytest

from app.sources.property.kleinanzeigen_de import (
    KleinanzeigenGermanyPropertySource,
    parse_kleinanzeigen_search_page,
)


def _page_html() -> str:
    return """
    <html><body>
      <h1>Häuser zum Kauf 1 - 25 von 200.707 Ergebnissen in Deutschland</h1>
      <article class="aditem" data-adid="3516307594">
        <div class="location">78098 Triberg</div>
        <img
          src="https://img.kleinanzeigen.test/house-320.jpg"
          srcset="https://img.kleinanzeigen.test/house-320.jpg 320w, https://img.kleinanzeigen.test/house-720.jpg 720w, https://img.kleinanzeigen.test/house-1400.jpg 1400w"
          alt="Tolle Aussicht, ruhige Lage!"
        >
        <h2><a href="/s-anzeige/tolle-aussicht-ruhige-lage-/3516307594-208-8530">
          Tolle Aussicht, ruhige Lage!
        </a></h2>
        <p>Großzügiges Einfamilienhaus auf drei Etagen...</p>
        <div>180 m² · 7 Zi.</div>
        <div>185.000 €</div>
      </article>
      <article class="aditem" data-adid="3516307595">
        <div class="location">84130 Dingolfing</div>
        <h2><a href="/s-anzeige/teures-haus/3516307595-208-1234">Teures Haus</a></h2>
        <div>174 m² · 5 Zi.</div>
        <div>662.900 €</div>
      </article>
    </body></html>
    """


def test_parser_extracts_minimal_public_card_facts_and_budget_filters() -> None:
    page = parse_kleinanzeigen_search_page(
        _page_html(),
        page_url="https://www.kleinanzeigen.de/s-haus-kaufen/anzeige:angebote/c208",
    )

    assert page.source_reported_count == 200707
    assert page.cards_seen == page.cards_parsed == 2
    assert page.out_of_budget_cards == 1
    assert len(page.items) == 1

    item = page.items[0]
    assert item.source_listing_id == "3516307594"
    assert item.url == (
        "https://www.kleinanzeigen.de/s-anzeige/"
        "tolle-aussicht-ruhige-lage-/3516307594-208-8530"
    )
    assert item.title == "Tolle Aussicht, ruhige Lage!"
    assert item.postal_code == "78098"
    assert item.city == "Triberg"
    assert item.price_eur == Decimal(185000)
    assert item.living_area_m2 == Decimal(180)
    assert item.plot_area_m2 is None
    assert item.description is None
    assert item.raw_payload["frontier_only"] is True
    assert item.raw_payload["thumbnail_url"] == (
        "https://img.kleinanzeigen.test/house-720.jpg"
    )
    assert item.raw_payload["thumbnail_semantics"] == "source_search_card"


def test_pagination_uses_current_public_route_shape() -> None:
    source = KleinanzeigenGermanyPropertySource(frontier_pages=3)

    assert len(source.default_shards()) == 1
    assert source._page_url(1) == (
        "https://www.kleinanzeigen.de/s-haus-kaufen/anzeige:angebote/c208"
    )
    assert source._page_url(2) == (
        "https://www.kleinanzeigen.de/s-haus-kaufen/seite:2/anzeige:angebote/c208"
    )


@pytest.mark.asyncio
async def test_frontier_never_claims_reconciliation_authority(monkeypatch) -> None:
    response = httpx.Response(
        200,
        text=_page_html(),
        request=httpx.Request(
            "GET",
            "https://www.kleinanzeigen.de/s-haus-kaufen/anzeige:angebote/c208",
        ),
    )

    class Probe(KleinanzeigenGermanyPropertySource):
        async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
            del client, url
            return response

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(
        "app.sources.property.kleinanzeigen_de.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )

    source = Probe(frontier_pages=1, hard_max_pages=40)
    batch = await source.fetch_shard(source.default_shards()[0], reconciliation=True)

    assert batch.coverage_complete is False
    assert batch.result_cap_hit is True
    assert batch.pages_fetched == 1
    assert len(batch.items) == 1
