from decimal import Decimal

import httpx
import pytest

from app.sources.property.falc_de import (
    FalcGermanyPropertySource,
    parse_falc_detail_identity,
    parse_falc_search_page,
)


def _search_html() -> str:
    return """
    <html><body>
      <h1>Haus zum Kauf finden</h1>
      <div>914 Immobilien gefunden</div>
      <article>
        <div>23992 Zurow - Deutschland - Mecklenburg-Vorpommern - Nordwestmecklenburg - Zurow</div>
        <img srcset="https://img.falc.test/a-320.jpg 320w, https://img.falc.test/a-720.jpg 720w">
        <h2><a href="/immobilie/landliches-wohnen-mit-viel-platz.html">
          Ländliches Wohnen mit viel Platz, Garten und Ausbaupotenzial
        </a></h2>
        <div>Wohnfläche 74,00 m²</div>
        <div>Grundstücksfläche 3.400,00 m²</div>
        <div>Objektart Haus</div>
        <div>Kaufpreis 119.000 €</div>
      </article>
      <article>
        <div>44328 Dortmund - Deutschland - Nordrhein-Westfalen - Dortmund</div>
        <h2><a href="/immobilie/jung-kauft-alt.html">Jung kauft Alt</a></h2>
        <div>Wohnfläche 71,00 m²</div>
        <div>Objektart Reihenmittelhaus</div>
        <div>Kaufpreis 179.000 €</div>
      </article>
      <article>
        <div>26215 Wiefelstede - Deutschland - Niedersachsen - Ammerland</div>
        <h2><a href="/immobilie/resthof-reserviert.html">Reserviert - Resthof mit Scheune</a></h2>
        <div>Wohnfläche 262,00 m²</div>
        <div>Objektart Haus</div>
        <div>Kaufpreis 190.000 €</div>
      </article>
      <article>
        <div>61440 Oberursel - Deutschland - Hessen - Hochtaunuskreis</div>
        <h2><a href="/immobilie/teures-townhouse.html">Traumhaftes Townhouse</a></h2>
        <div>Wohnfläche 97,00 m²</div>
        <div>Objektart Stadthaus</div>
        <div>Kaufpreis 671.000 €</div>
      </article>
    </body></html>
    """


def _detail_html(listing_id: str, heating: str = "Öl") -> str:
    return f"""
    <html><body>
      <h1>Objekt</h1>
      <div>Objektnr. {listing_id}</div>
      <section>
        <div>Heizungsart:</div><div>Ofen</div>
        <div>Befeuerung:</div><div>{heating}</div>
      </section>
      <p>Full description that must not be retained.</p>
    </body></html>
    """


def test_falc_search_parser_filters_budget_and_unavailable_cards() -> None:
    page = parse_falc_search_page(
        _search_html(),
        page_url="https://www.falcimmo.de/haeuser-zum-kauf.html",
    )

    assert page.source_reported_count == 914
    assert page.cards_seen == page.cards_parsed == 4
    assert page.unavailable_cards == 1
    assert page.out_of_budget_cards == 1
    assert len(page.candidates) == 2

    item = page.candidates[0]
    assert item.url == (
        "https://www.falcimmo.de/immobilie/"
        "landliches-wohnen-mit-viel-platz.html"
    )
    assert item.title == "Ländliches Wohnen mit viel Platz, Garten und Ausbaupotenzial"
    assert item.postal_code == "23992"
    assert item.city == "Zurow"
    assert item.price_eur == Decimal(119000)
    assert item.living_area_m2 == Decimal(74)
    assert item.plot_area_m2 == Decimal(3400)
    assert item.thumbnail_url == "https://img.falc.test/a-720.jpg"


def test_falc_detail_identity_is_explicit_object_number() -> None:
    assert parse_falc_detail_identity(
        _detail_html("FALC-CaMa-90564")
    ) == "FALC-CAMA-90564"


def test_falc_pagination_uses_current_public_route() -> None:
    source = FalcGermanyPropertySource(frontier_pages=3)

    assert len(source.default_shards()) == 1
    assert source._page_url(1) == "https://www.falcimmo.de/haeuser-zum-kauf.html"
    assert source._page_url(2) == (
        "https://www.falcimmo.de/haeuser-zum-kauf.html?page_n47=2"
    )


@pytest.mark.asyncio
async def test_falc_frontier_materializes_stable_ids_and_never_reconciles(monkeypatch) -> None:
    search_response = httpx.Response(
        200,
        text=_search_html(),
        request=httpx.Request(
            "GET", "https://www.falcimmo.de/haeuser-zum-kauf.html"
        ),
    )
    detail_by_url = {
        "https://www.falcimmo.de/immobilie/landliches-wohnen-mit-viel-platz.html":
            _detail_html("FALC-CaMa-90564", "Öl"),
        "https://www.falcimmo.de/immobilie/jung-kauft-alt.html":
            _detail_html("FALC-NRW-12345", "Gas"),
    }

    class Probe(FalcGermanyPropertySource):
        async def _get(self, client, url):
            del client
            if url == self._page_url(1):
                return search_response
            return httpx.Response(
                200,
                text=detail_by_url[url],
                request=httpx.Request("GET", url),
            )

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(
        "app.sources.property.falc_de.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )

    source = Probe(frontier_pages=1)
    batch = await source.fetch_shard(source.default_shards()[0], reconciliation=True)

    assert batch.coverage_complete is False
    assert batch.result_cap_hit is True
    assert batch.pages_fetched == 1
    assert {item.source_listing_id for item in batch.items} == {
        "FALC-CAMA-90564",
        "FALC-NRW-12345",
    }
    first = next(item for item in batch.items if item.source_listing_id == "FALC-CAMA-90564")
    assert first.raw_payload["source_object_number"] == "FALC-CAMA-90564"
    assert first.raw_payload["heating_types"] == ["oil"]
    assert first.description is None
    assert "Full description" not in str(first.raw_payload)
