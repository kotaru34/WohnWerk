from __future__ import annotations

import json
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.sources.property.immoscout24_de import (
    ImmoScout24GermanyPropertySource,
    parse_immoscout24_search_page,
)


def _page_html(*, total: int = 1, listing_id: str = "170458914") -> str:
    context = {
        "filters": {
            "locations": [{"label": "Sachsen", "type": "region"}],
            "price": "30.000 bis 149.999 €",
        },
        "search_result_list": [
            {
                "expose_id": listing_id,
                "title": "Kleines Haus am Elbhang",
                "price": "135.000 €",
                "address": {"postcode": "01067", "city": "Dresden"},
                "living_space": "106,18 m²",
                "ground_area": "581 m²",
                "number_of_rooms": "6",
            }
        ],
    }
    encoded_context = json.dumps(json.dumps(context, ensure_ascii=False))
    return f"""
        <html><body>
          <h1 data-testid="ResultListHeadline"><span>{total}</span> Häuser zum Kauf</h1>
          <button page="1" data-testid="pagination-button">1</button>
          <script>{{"heyImmoContext":{encoded_context}}}</script>
        </body></html>
    """


def test_parser_keeps_only_minimal_public_facts_and_leading_zero_plz() -> None:
    page = parse_immoscout24_search_page(
        _page_html(),
        page_url="https://www.immobilienscout24.de/Suche/de/sachsen/haus-kaufen",
        region_key="sachsen",
        price_band_key="030000-149999",
    )

    assert page.source_reported_count == 1
    assert page.cards_seen == page.cards_parsed == 1
    item = page.items[0]
    assert item.source_listing_id == "170458914"
    assert item.url == "https://www.immobilienscout24.de/expose/170458914"
    assert item.price_eur == Decimal(135000)
    assert item.living_area_m2 == Decimal("106.18")
    assert item.plot_area_m2 == Decimal(581)
    assert item.postal_code == "01067"
    assert item.city == "Dresden"
    assert item.description is None
    assert "contact" not in item.raw_payload
    assert "image" not in item.raw_payload
    assert item.raw_payload["country_code"] == "DE"


def test_shards_cover_states_and_non_overlapping_budget_bands() -> None:
    source = ImmoScout24GermanyPropertySource()
    shards = source.default_shards()

    assert len(shards) == 48
    assert len({shard.key for shard in shards}) == 48
    url = source._page_url("nordrhein-westfalen", "225000-300000", 2)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.path == "/Suche/de/nordrhein-westfalen/haus-kaufen"
    assert query["price"] == ["225000-300000.0"]
    assert query["sorting"] == ["2"]
    assert query["pagenumber"] == ["2"]


@pytest.mark.asyncio
async def test_plain_http_401_switches_to_reused_stock_browser_transport(monkeypatch) -> None:
    url = "https://www.immobilienscout24.de/Suche/de/sachsen/haus-kaufen"

    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        async def get(self, requested_url: str) -> httpx.Response:
            self.calls += 1
            return httpx.Response(
                401,
                text="unauthorized",
                request=httpx.Request("GET", requested_url),
            )

    class ProbeSource(ImmoScout24GermanyPropertySource):
        def __init__(self) -> None:
            super().__init__()
            self.browser_calls = 0

        async def _sleep(self) -> None:
            return None

        async def _get_with_browser(self, requested_url: str) -> httpx.Response:
            self.browser_calls += 1
            return httpx.Response(
                200,
                text=_page_html(),
                request=httpx.Request("GET", requested_url),
            )

    source = ProbeSource()
    client = FakeClient()

    first = await source._get(client, url)
    second = await source._get(client, url)

    assert first.status_code == second.status_code == 200
    assert source._browser_required is True
    assert client.calls == 1
    assert source.browser_calls == 2


@pytest.mark.asyncio
async def test_single_page_reconciliation_is_authoritative(monkeypatch) -> None:
    url = "https://www.immobilienscout24.de/Suche/de/sachsen/haus-kaufen"
    response = httpx.Response(200, text=_page_html(), request=httpx.Request("GET", url))

    class ProbeSource(ImmoScout24GermanyPropertySource):
        async def _get(self, client: httpx.AsyncClient, requested_url: str) -> httpx.Response:
            del client, requested_url
            return response

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(
        "app.sources.property.immoscout24_de.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )

    source = ProbeSource(request_delay_seconds=1.0)
    shard = next(shard for shard in source.default_shards() if shard.key.startswith("sachsen:"))
    batch = await source.fetch_shard(shard, reconciliation=True)

    assert batch.coverage_complete is True
    assert batch.result_cap_hit is False
    assert batch.pages_fetched == 1
    assert batch.next_cursor["discovery_count_delta"] == 0
    assert batch.next_cursor["discovery_transport"] == "httpx"
