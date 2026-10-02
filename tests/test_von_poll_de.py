from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from app.sources.property.von_poll_de import (
    VonPollGermanyPropertySource,
    parse_von_poll_search_page,
)


def _page_html(*, count: int = 2) -> str:
    return f"""
    <html><body>
      <h1>Haus kaufen in Bayern</h1>
      <div>1 – 20 von {count} Treffer(n)</div>
      <a href="/de/expose/regensburg/kleines-holzhaus-mit-garten-111001535227">
        95615 Marktredwitz – Bayern Kleines Holzhaus mit Garten
        5 Zi. ca. 112 m² ca. 640 m² 189.000 EUR
      </a>
      <a href="/de/expose/regensburg/reserviert-teure-villa-111001535228">
        93155 Hemau – Bayern Reserviert - Teure Villa
        9 Zi. ca. 220 m² ca. 987 m² 445.000 EUR
      </a>
    </body></html>
    """


def test_parser_keeps_available_budget_house_and_skips_reserved_inventory() -> None:
    page = parse_von_poll_search_page(
        _page_html(),
        page_url="https://www.von-poll.com/de/haus-kaufen/bayern",
        region_key="bayern",
    )

    assert page.source_reported_count == 2
    assert page.cards_seen == page.cards_parsed == 2
    assert page.unavailable_cards == 1
    assert page.out_of_budget_cards == 0
    assert len(page.items) == 1

    item = page.items[0]
    assert item.source_listing_id == "111001535227"
    assert item.url == (
        "https://www.von-poll.com/de/expose/regensburg/"
        "kleines-holzhaus-mit-garten-111001535227"
    )
    assert item.postal_code == "95615"
    assert item.city == "Marktredwitz"
    assert item.title == "Kleines Holzhaus mit Garten"
    assert item.price_eur == Decimal(189000)
    assert item.living_area_m2 == Decimal(112)
    assert item.plot_area_m2 == Decimal(640)
    assert item.description is None
    assert item.raw_payload["country_code"] == "DE"
    assert item.raw_payload["source_status"] == "available"


def test_parser_skips_available_but_out_of_budget_house() -> None:
    html = _page_html().replace("189.000 EUR", "289.000 EUR")
    page = parse_von_poll_search_page(
        html,
        page_url="https://www.von-poll.com/de/haus-kaufen/bayern",
        region_key="bayern",
    )

    assert page.items == []
    assert page.out_of_budget_cards == 1
    assert page.unavailable_cards == 1
    assert page.cards_seen == page.cards_parsed == 2


def test_state_shards_and_public_pagination_are_deterministic() -> None:
    source = VonPollGermanyPropertySource()

    assert len(source.default_shards()) == 16
    assert source._page_url("bayern", 1) == "https://www.von-poll.com/de/haus-kaufen/bayern"
    assert source._page_url("bayern", 2) == (
        "https://www.von-poll.com/de/haus-kaufen/bayern?page=2"
    )


@pytest.mark.asyncio
async def test_complete_single_page_reconciliation_is_authoritative(monkeypatch) -> None:
    response = httpx.Response(
        200,
        text=_page_html(),
        request=httpx.Request("GET", "https://www.von-poll.com/de/haus-kaufen/bayern"),
    )

    class ProbeSource(VonPollGermanyPropertySource):
        async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
            del client, url
            return response

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(
        "app.sources.property.von_poll_de.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )

    source = ProbeSource(request_delay_seconds=2.0)
    shard = next(shard for shard in source.default_shards() if shard.key == "bayern")
    batch = await source.fetch_shard(shard, reconciliation=True)

    assert batch.coverage_complete is True
    assert batch.result_cap_hit is False
    assert batch.pages_fetched == 1
    assert len(batch.items) == 1
    assert batch.next_cursor["discovery_unavailable_cards"] == 1
