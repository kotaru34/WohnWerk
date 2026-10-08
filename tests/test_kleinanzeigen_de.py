from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.sources.base import SourceFetchError
from app.sources.property.kleinanzeigen_de import (
    REGIONAL_PILOT,
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


def test_regional_pilot_has_four_validated_public_state_frontiers() -> None:
    national = KleinanzeigenGermanyPropertySource(frontier_pages=12)
    assert [s.key for s in national.default_shards()] == ["de-newest-frontier"]

    pilot = KleinanzeigenGermanyPropertySource(frontier_pages=3, regional_pilot=True)
    shards = pilot.default_shards()
    assert len(shards) == 4
    assert {s.params["region_key"] for s in shards} == {
        "sachsen", "thueringen", "brandenburg", "nordrhein-westfalen"
    }
    assert all(s.params["country_code"] == "DE" for s in shards)
    assert sum([3] * len(shards)) == 12  # same number of pages as national baseline
    assert len(REGIONAL_PILOT) == len(shards)

    assert pilot._page_url(1, region_key="sachsen") == (
        "https://www.kleinanzeigen.de/s-haus-kaufen/"
        "sachsen/anzeige:angebote/c208l3799"
    )
    assert pilot._page_url(2, region_key="sachsen") == (
        "https://www.kleinanzeigen.de/s-haus-kaufen/"
        "sachsen/anzeige:angebote/seite:2/c208l3799"
    )


def test_parser_supports_actual_state_result_counts() -> None:
    html = _page_html().replace(
        "Häuser zum Kauf 1 - 25 von 200.707 Ergebnissen in Deutschland",
        "Häuser zum Kauf in Sachsen 1 - 25 von 9.865 Ergebnissen in Sachsen",
    )
    parsed = parse_kleinanzeigen_search_page(
        html,
        page_url="https://www.kleinanzeigen.de/s-haus-kaufen/"
        "sachsen/anzeige:angebote/c208l3799",
    )
    assert parsed.source_reported_count == 9865
    assert parsed.cards_seen == 2
    assert len(parsed.items) == 1


@pytest.mark.asyncio
async def test_regional_pilot_uses_independent_shard_pages_and_keeps_degraded(
    monkeypatch,
) -> None:
    requested = []
    class Probe(KleinanzeigenGermanyPropertySource):
        async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
            del client
            requested.append(url)
            region = next(key for key, _code, _label in REGIONAL_PILOT if f"/{key}/" in url)
            label = next(label for key, _code, label in REGIONAL_PILOT if key == region)
            return httpx.Response(
                200,
                text=_page_html().replace(
                    "Häuser zum Kauf 1 - 25 von 200.707 Ergebnissen in Deutschland",
                    f"Häuser zum Kauf in {label} 1 - 25 von 100 Ergebnissen in {label}",
                ),
                request=httpx.Request("GET", url),
            )

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(
        "app.sources.property.kleinanzeigen_de.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )

    pilot = Probe(frontier_pages=3, regional_pilot=True)
    batches = [
        await pilot.fetch_shard(shard, reconciliation=True)
        for shard in pilot.default_shards()
    ]
    assert len(requested) == 12
    assert all(not batch.coverage_complete and batch.result_cap_hit for batch in batches)
    assert all(batch.pages_fetched == 3 and len(batch.items) == 1 for batch in batches)
    assert all("region_key" in batch.next_cursor for batch in batches)
    assert len({b.next_cursor["region_key"] for b in batches}) == 4


@pytest.mark.asyncio
async def test_region_pilot_fails_closed_when_scope_redirects_to_nationwide(
    monkeypatch,
) -> None:
    class Misrouted(KleinanzeigenGermanyPropertySource):
        async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
            del client, url
            return httpx.Response(
                200,
                text=_page_html(),
                request=httpx.Request(
                    "GET", "https://www.kleinanzeigen.de/s-haus-kaufen/"
                    "anzeige:angebote/c208"
                ),
            )

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(
        "app.sources.property.kleinanzeigen_de.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )
    pilot = Misrouted(frontier_pages=3, regional_pilot=True)
    with pytest.raises(SourceFetchError, match="scope was lost") as err:
        await pilot.fetch_shard(pilot.default_shards()[0])
    assert err.value.halt_source is True
    assert err.value.pages_fetched == 0
    assert err.value.items_seen == 0


def test_hybrid_keeps_national_plus_four_regions_and_rejects_mutually_exclusive_modes() -> None:
    hybrid = KleinanzeigenGermanyPropertySource(
        frontier_pages=12, regional_expansion=True,
    )
    shards = hybrid.default_shards()
    assert len(shards) == 5
    assert shards[0].key == "de-newest-frontier"
    assert shards[0].params == {"country_code": "DE"}
    assert {spec.key for spec in shards[1:]} == {
        f"de-region-{key}" for key, _code, _label in REGIONAL_PILOT
    }
    assert hybrid._page_url(1) == KleinanzeigenGermanyPropertySource._page_url(1)
    with pytest.raises(ValueError, match="mutually exclusive"):
        KleinanzeigenGermanyPropertySource(regional_pilot=True, regional_expansion=True)


@pytest.mark.asyncio
async def test_hybrid_budget_is_12_national_plus_3_per_region(monkeypatch) -> None:
    requested: list[str] = []

    class Probe(KleinanzeigenGermanyPropertySource):
        async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
            del client
            requested.append(url)
            region = next(
                (key for key, _code, _label in REGIONAL_PILOT if f"/{key}/" in url),
                None,
            )
            heading = (
                "Häuser zum Kauf 1 - 25 von 200.707 Ergebnissen in Deutschland"
            )
            if region is None:
                html = _page_html()
            else:
                label = next(label for key, _code, label in REGIONAL_PILOT if key == region)
                html = _page_html().replace(
                    heading, f"Häuser zum Kauf in {label} 1 - 25 von 100 Ergebnissen"
                    f" in {label}",
                )
            return httpx.Response(200, text=html, request=httpx.Request("GET", url))

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(
        "app.sources.property.kleinanzeigen_de.httpx.AsyncClient",
        lambda **_kwargs: FakeClient(),
    )

    hybrid = Probe(frontier_pages=12, regional_expansion=True)
    batches = [
        await hybrid.fetch_shard(spec) for spec in hybrid.default_shards()
    ]
    assert len(batches) == 5
    assert [batch.pages_fetched for batch in batches] == [12, 3, 3, 3, 3]
    assert all(batch.coverage_complete is False for batch in batches)
    assert all(batch.result_cap_hit is True for batch in batches)
    assert len(requested) == 24
    assert all("/s-haus-kaufen/seite:" in url for url in requested[1:12])
    assert any("/s-haus-kaufen/sachsen/" in url for url in requested[12:])


def test_runner_persists_hybrid_enablement_across_scheduled_invocations(monkeypatch) -> None:
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_kleinanzeigen_de.py"
    spec = spec_from_file_location("kleinanzeigen_runner_test", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    source = SimpleNamespace(
        id=444,
        enabled=True,
        config={
            "country_code": "DE",
            "regional_expansion_enabled": False,
            "operator_custom": "preserve-me",
        },
    )

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def scalar(self, _query):
            return source

        def commit(self) -> None:
            pass

    monkeypatch.setattr(module, "SessionLocal", lambda: FakeSession())
    assert module.get_or_create_source() == 444
    assert source.config["regional_expansion_enabled"] is False
    assert module.get_or_create_source(enable_regional_expansion=True) == 444
    assert source.config["regional_expansion_enabled"] is True
    assert module.get_or_create_source() == 444
    assert source.config["regional_expansion_enabled"] is True
    assert source.config["operator_custom"] == "preserve-me"
