from decimal import Decimal

import httpx
import pytest

from app.sources.base import SourceFetchError
from app.sources.property.remax_de import (
    RemaxGermanyPropertySource,
    _is_access_challenge,
    parse_remax_search_page,
)


def _page_html() -> str:
    return """
    <html><body>
      <h1>42 Häuser in Bayern zu kaufen und zu mieten</h1>
      <article>
        <div>Lage: 66709 Thailen-Weiskirchen Haus: 1155-123-NR</div>
        <img srcset="https://img.remax.test/a-320.jpg 320w, https://img.remax.test/a-720.jpg 720w">
        <h2><a href="/de/1155-123-nr">Freistehendes Haus mit großem Grundstück</a></h2>
        <a href="/de/natalya-rodermel">Natalya Rodermel</a>
        <div>EUR 99.000 Kaufpreis</div>
        <div>182,38 m² Wohnfläche</div>
      </article>
      <article>
        <div>Lage: 94469 Deggendorf Haus: 9999-999-NR</div>
        <h2><a href="/de/9999-999-nr">Teures Haus</a></h2>
        <div>EUR 490.000 Kaufpreis</div>
        <div>160 m² Wohnfläche</div>
      </article>
      <article>
        <div>Lage: 86150 Augsburg Haus: 8888-888-NR</div>
        <h2><a href="/de/8888-888-nr">Haus zur Miete</a></h2>
        <div>EUR 1.400 Kaltmiete</div>
        <div>120 m² Wohnfläche</div>
      </article>
    </body></html>
    """


def test_parser_extracts_budget_purchase_and_preserves_remax_object_id() -> None:
    page = parse_remax_search_page(
        _page_html(),
        page_url="https://www.remax.de/de/l/ol/haeuser-bayern",
    )

    assert page.source_reported_count == 42
    assert page.cards_seen == page.cards_parsed == 3
    assert page.rental_cards == 1
    assert page.out_of_budget_cards == 1
    assert len(page.items) == 1

    item = page.items[0]
    assert item.source_listing_id == "1155-123-NR"
    assert item.url == "https://www.remax.de/de/1155-123-nr"
    assert item.title == "Freistehendes Haus mit großem Grundstück"
    assert item.postal_code == "66709"
    assert item.city == "Thailen-Weiskirchen"
    assert item.price_eur == Decimal(99000)
    assert item.living_area_m2 == Decimal("182.38")
    assert item.plot_area_m2 is None
    assert item.raw_payload["frontier_only"] is True
    assert item.raw_payload["thumbnail_url"] == "https://img.remax.test/a-720.jpg"


def test_parser_ignores_broker_profile_links_inside_property_card() -> None:
    page = parse_remax_search_page(
        _page_html(),
        page_url="https://www.remax.de/de/l/ol/haeuser-bayern",
    )

    assert page.cards_seen == page.cards_parsed == 3
    assert [item.source_listing_id for item in page.items] == ["1155-123-NR"]


def test_turnstile_security_page_is_detected() -> None:
    assert _is_access_challenge(
        '<h1>Security Verification</h1>'
        '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>'
        '<div class="cf-turnstile"></div>'
    )


@pytest.mark.asyncio
async def test_remax_get_fails_closed_on_turnstile() -> None:
    response = httpx.Response(
        200,
        text=(
            '<h1>Security Verification</h1>'
            '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>'
        ),
        request=httpx.Request("GET", "https://www.remax.de/de/l/ol/haeuser-saarland"),
    )

    class FakeClient:
        async def get(self, _url):
            return response

    source = RemaxGermanyPropertySource()

    with pytest.raises(SourceFetchError) as raised:
        await source._get(FakeClient(), "https://www.remax.de/de/l/ol/haeuser-saarland")

    assert raised.value.halt_source is True
    assert "challenge" in str(raised.value).casefold()


def test_remax_uses_all_german_regions_as_bounded_frontier_shards() -> None:
    source = RemaxGermanyPropertySource()

    shards = source.default_shards()
    assert len(shards) == 16
    bayern = next(shard for shard in shards if shard.key == "bayern")
    assert source._shard_url(bayern) == "https://www.remax.de/de/l/ol/haeuser-bayern"


@pytest.mark.asyncio
async def test_remax_frontier_never_claims_reconciliation_authority(monkeypatch) -> None:
    response = httpx.Response(
        200,
        text=_page_html(),
        request=httpx.Request("GET", "https://www.remax.de/de/l/ol/haeuser-bayern"),
    )

    class Probe(RemaxGermanyPropertySource):
        def default_shards(self):
            return [super().default_shards()[1]]

        async def _get(self, client, url):
            del client, url
            return response

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(
        "app.sources.property.remax_de.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )

    source = Probe()
    batch = await source.fetch_shard(source.default_shards()[0], reconciliation=True)

    assert batch.coverage_complete is False
    assert batch.result_cap_hit is True
    assert batch.pages_fetched == 1
    assert len(batch.items) == 1
