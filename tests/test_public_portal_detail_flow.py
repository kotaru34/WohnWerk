"""Offline, transport-mocked checks of public-card -> detail -> visibility gates."""

from decimal import Decimal

import httpx
import pytest

from app.property_acquisition import annotate_property_items_by_budget
from app.sources.base import SourceFetchError
from app.sources.property import public_portals_de as portals

FRONTIER = """
<main><article>
<a href="/immobilie/503161/">120.000 € Haus mit Scheune und Garten
17213 Fünfseen 5 145m² 800m²</a>
</article></main>
"""
DETAIL = """
<main>
<h1>Haus mit Scheune und Garten</h1>
<p>17213 Fünfseen</p><p>Objekt-Nr OM-503161</p>
<p>Kaufpreis | 120.000 €</p>
<p>Wohnfläche 145 m² Grundstücksfläche 800 m² Baujahr 1980</p>
</main>
"""


@pytest.mark.asyncio
async def test_public_cards_never_appear_as_verified_houses_without_detail(
    monkeypatch,
) -> None:
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, text=FRONTIER, headers={"Content-Type": "text/html"})

    original = httpx.AsyncClient
    monkeypatch.setattr(portals.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw
    ))
    monkeypatch.setattr(portals.asyncio, "sleep", _no_sleep)

    adapter = portals.OhneMaklerGermanyPropertySource(
        verify_details=False, delay_seconds=0
    )
    batch = await adapter.fetch_shard(adapter.default_shards()[0])
    assert paths == [portals.OHNE_MAKLER.search_path]
    assert len(batch.items) == 1
    item = batch.items[0]
    assert item.price_eur == Decimal(120000)
    assert item.raw_payload["public_house_detail_verified"] is False
    annotate_property_items_by_budget(batch.items)
    assert item.raw_payload["product_visible"] is False
    assert item.raw_payload["product_visibility_reason"] == "house_detail_unverified"


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_verified_existing_house_can_be_shown_after_bounded_detail_check(
    monkeypatch,
) -> None:
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(
            200, text=DETAIL if "/immobilie/" in request.url.path else FRONTIER,
            headers={"Content-Type": "text/html"},
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(portals.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw
    ))
    monkeypatch.setattr(portals.asyncio, "sleep", _no_sleep)

    adapter = portals.OhneMaklerGermanyPropertySource(
        verify_details=True, max_detail_checks_per_shard=1
    )
    batch = await adapter.fetch_shard(adapter.default_shards()[0])
    assert paths == [portals.OHNE_MAKLER.search_path, "/immobilie/503161/"]
    assert len(batch.items) == 1
    assert batch.pages_fetched == 2
    assert batch.next_cursor["detail_verified"] == 1
    annotate_property_items_by_budget(batch.items)
    assert batch.items[0].raw_payload["product_visible"] is True
    assert batch.items[0].raw_payload["public_house_detail_reason"] == (
        "verified_existing_house"
    )


@pytest.mark.asyncio
async def test_builder_brochure_is_kept_as_hidden_unverified_observation(
    monkeypatch,
) -> None:
    detail = DETAIL.replace(
        "Baujahr 1980", "Baujahr 1980. Bauleistungsbeschreibung Hausbauvertrag"
    )

    def handler(request):
        return httpx.Response(
            200, text=detail if "/immobilie/" in request.url.path else FRONTIER,
            headers={"Content-Type": "text/html"},
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(portals.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw
    ))
    monkeypatch.setattr(portals.asyncio, "sleep", _no_sleep)
    adapter = portals.OhneMaklerGermanyPropertySource(verify_details=True)
    batch = await adapter.fetch_shard(adapter.default_shards()[0])
    assert batch.next_cursor["detail_checked"] == 1
    assert batch.next_cursor["detail_verified"] == 0
    assert batch.items[0].raw_payload["public_house_detail_reason"] == (
        "construction_only"
    )
    annotate_property_items_by_budget(batch.items)
    assert batch.items[0].raw_payload["product_visible"] is False


@pytest.mark.asyncio
async def test_public_detail_access_gate_aborts_source_without_solving_challenge(
    monkeypatch,
) -> None:
    def handler(request):
        if "/immobilie/" in request.url.path:
            return httpx.Response(429, text="Too Many Requests")
        return httpx.Response(200, text=FRONTIER, headers={"Content-Type": "text/html"})

    original = httpx.AsyncClient
    monkeypatch.setattr(portals.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw
    ))
    monkeypatch.setattr(portals.asyncio, "sleep", _no_sleep)
    adapter = portals.OhneMaklerGermanyPropertySource(verify_details=True)
    with pytest.raises(SourceFetchError) as exc_info:
        await adapter.fetch_shard(adapter.default_shards()[0])
    assert exc_info.value.halt_source is True
    assert exc_info.value.pages_fetched == 2
    assert len(exc_info.value.partial_items) == 1
    assert exc_info.value.partial_items[0].raw_payload["public_house_detail_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429, 503])
async def test_public_search_access_denial_halts_all_remaining_regional_shards(
    monkeypatch, status: int,
) -> None:
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(status, text="Access restriction")

    original = httpx.AsyncClient
    monkeypatch.setattr(portals.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw
    ))
    monkeypatch.setattr(portals.asyncio, "sleep", _no_sleep)

    adapter = portals.OhneMaklerGermanyPropertySource()
    assert len(adapter.default_shards()) >= 2
    with pytest.raises(SourceFetchError) as exc_info:
        await adapter.fetch_shard(adapter.default_shards()[0])
    assert exc_info.value.halt_source is True
    assert paths == [portals.OHNE_MAKLER.search_path]


@pytest.mark.asyncio
async def test_search_challenge_page_fails_closed_and_prevents_regional_retries(
    monkeypatch,
) -> None:
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, text="<html><body>Security Verification CAPTCHA</body></html>",
            headers={"Content-Type": "text/html"},
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(portals.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw
    ))
    monkeypatch.setattr(portals.asyncio, "sleep", _no_sleep)
    adapter = portals.OhneMaklerGermanyPropertySource()
    with pytest.raises(SourceFetchError) as exc_info:
        await adapter.fetch_shard(adapter.default_shards()[0])
    assert exc_info.value.halt_source is True
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_search_json_payload_is_not_trusted_as_public_html(monkeypatch) -> None:
    original = httpx.AsyncClient
    monkeypatch.setattr(portals.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"cards": [], "status": "OK"}
            )
        ), **kw
    ))
    monkeypatch.setattr(portals.asyncio, "sleep", _no_sleep)
    adapter = portals.OhneMaklerGermanyPropertySource()
    with pytest.raises(SourceFetchError):
        await adapter.fetch_shard(adapter.default_shards()[0])


@pytest.mark.asyncio
async def test_detail_returning_non_html_cannot_verify_house(monkeypatch) -> None:
    def handler(request):
        if "/immobilie/" in request.url.path:
            return httpx.Response(
                200,
                text=DETAIL,
                headers={"Content-Type": "application/json"},
            )
        return httpx.Response(
            200, text=FRONTIER, headers={"Content-Type": "text/html"}
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(portals.httpx, "AsyncClient", lambda **kw: original(
        transport=httpx.MockTransport(handler), **kw
    ))
    monkeypatch.setattr(portals.asyncio, "sleep", _no_sleep)
    adapter = portals.OhneMaklerGermanyPropertySource(verify_details=True)
    batch = await adapter.fetch_shard(adapter.default_shards()[0])
    assert batch.next_cursor["detail_verified"] == 0
    assert batch.items[0].raw_payload["public_house_detail_verified"] is False
    assert batch.items[0].raw_payload["public_house_detail_reason"] == (
        "detail_unavailable"
    )
