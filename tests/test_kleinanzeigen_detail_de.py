"""Offline regression fixtures based on user-reported and public DE adverts.

No live network access, credentials, seller contacts, or archived full ads.
"""

from decimal import Decimal

import pytest

from app.sources.property.kleinanzeigen_detail_de import (
    parse_kleinanzeigen_house_detail,
)

USLAR_ID = "3439264864"
USLAR_URL = (
    "https://www.kleinanzeigen.de/s-anzeige/"
    "ihr-neues-zuhause-zum-verwirklichen-reihenmittelhaus-mit-terrasse-und-garage-in-uslar/"
    "3439264864-208-2782"
)
RAVENSTEIN_ID = "3377512338"
RAVENSTEIN_URL = (
    "https://www.kleinanzeigen.de/s-anzeige/"
    "platz-fuer-ideen-familie-und-zukunft/3377512338-208-9252"
)


def detail_html(*, plot: str, description: str, identity: str) -> str:
    return f"""
    <html><body>
      <h1>Ihr neues Zuhause</h1>
      <ul><li><span>Wohnfläche</span><span>81,96 m²</span></li>
          <li><span>Grundstücksfläche</span><span>{plot}</span></li></ul>
      <h2>Beschreibung</h2><p>{description}</p>
      <h2>Nachricht schreiben</h2>
      <h3>Andere Anzeigen des Anbieters</h3>
      <p>Grundstücksfläche: 20.000 m² Gasheizung Öl</p>
      <span>Anzeigen-ID</span><span>{identity}</span>
    </body></html>
    """


def test_uslar_live_public_evidence_yields_gas_and_217_square_metres() -> None:
    # Actual public advert has Gasheizung aus 2010 and
    # Wesentliche Energieträger: GAS; plot=217 m².
    html = detail_html(
        plot="217 m²",
        description=(
            "Die vorhandene Gasheizung stammt aus dem Jahr 2010. "
            "Wesentliche Energieträger: GAS. Heizungsart: Zentralheizung."
        ),
        identity=USLAR_ID,
    )
    facts = parse_kleinanzeigen_house_detail(html, url=USLAR_URL, expected_listing_id=USLAR_ID)
    assert facts.listing_id == USLAR_ID
    assert facts.plot_area_m2 == Decimal(217)
    assert facts.heating.types == ("gas",)
    assert "Grundstücksfläche" in facts.plot_evidence


def test_ravenstein_electroenergie_nachtspeicher_and_land_328() -> None:
    html = detail_html(
        plot="ca. 328 m²",
        description=(
            "Elektronachtspeicher und Kachelofen. "
            "Wesentliche Energieträger: Elektroenergie, Holz. "
            "Heizungsart: Ofenheizung."
        ),
        identity=RAVENSTEIN_ID,
    )
    facts = parse_kleinanzeigen_house_detail(
        html, url=RAVENSTEIN_URL, expected_listing_id=RAVENSTEIN_ID,
    )
    assert facts.plot_area_m2 == Decimal(328)
    assert facts.heating.types == ("wood", "electric")


def test_value_first_style_not_mistaken_for_living_area_or_useable_area() -> None:
    html = detail_html(
        plot="1.234,5 qm",
        description="Wohnfläche 180 m². Nutzfläche 400 m².",
        identity=USLAR_ID,
    )
    facts = parse_kleinanzeigen_house_detail(html, url=USLAR_URL, expected_listing_id=USLAR_ID)
    assert facts.plot_area_m2 == Decimal("1234.5")


@pytest.mark.parametrize("plot", ["0 m²", "2 m²", "200000 m²", "keine Angabe", "217 kWh"])
def test_invalid_plot_stays_unknown(plot: str) -> None:
    facts = parse_kleinanzeigen_house_detail(
        detail_html(plot=plot, description="Heizungsart: Zentralheizung", identity=USLAR_ID),
        url=USLAR_URL,
        expected_listing_id=USLAR_ID,
    )
    assert facts.plot_area_m2 is None
    assert facts.heating.types == ()


def test_conflicting_same_listing_plot_sizes_fail_closed() -> None:
    html = detail_html(
        plot="217 m²",
        description="Grundstücksfläche: ca. 600 m². Heizung Gastherme.",
        identity=USLAR_ID,
    )
    facts = parse_kleinanzeigen_house_detail(html, url=USLAR_URL, expected_listing_id=USLAR_ID)
    assert facts.plot_area_m2 is None
    assert facts.plot_evidence is None
    assert facts.heating.types == ("gas",)


def test_related_ads_and_seller_section_cannot_contribute_heating_or_plot() -> None:
    html = detail_html(
        plot="nicht bekannt",
        description="Gepflegtes Haus.",
        identity=USLAR_ID,
    )
    facts = parse_kleinanzeigen_house_detail(html, url=USLAR_URL, expected_listing_id=USLAR_ID)
    assert facts.plot_area_m2 is None
    assert facts.heating.types == ()


def test_detail_requires_matching_visible_identity_and_https_canonical_host() -> None:
    html = detail_html(plot="217 m²", description="Gasheizung", identity="9999999999")
    with pytest.raises(ValueError, match="identify"):
        parse_kleinanzeigen_house_detail(html, url=USLAR_URL, expected_listing_id=USLAR_ID)

    valid = detail_html(plot="217 m²", description="Gasheizung", identity=USLAR_ID)
    for url in [
        USLAR_URL.replace("https:", "http:"),
        USLAR_URL.replace("www.kleinanzeigen.de", "other.example"),
        USLAR_URL.replace(USLAR_ID, "9999999999"),
        USLAR_URL.replace("kleinanzeigen.de", "kleinanzeigen.de.evil.test"),
    ]:
        with pytest.raises(ValueError, match="untrusted"):
            parse_kleinanzeigen_house_detail(valid, url=url, expected_listing_id=USLAR_ID)


def test_deleted_page_does_not_count_as_confirmed_house() -> None:
    html = detail_html(plot="217 m²", description="Gasheizung", identity=USLAR_ID)
    html = html.replace("<h1>Ihr neues Zuhause</h1>", "<span>Gelöscht</span><h1>Ihr neues Zuhause</h1>")
    with pytest.raises(ValueError, match="deleted"):
        parse_kleinanzeigen_house_detail(html, url=USLAR_URL, expected_listing_id=USLAR_ID)


def test_script_payload_and_other_ad_before_contact_cannot_fake_id() -> None:
    html = detail_html(plot="217 m²", description="Gasheizung", identity="9999999999")
    html = html.replace(
        "<h1>Ihr neues Zuhause</h1>",
        f"<script>Anzeigen-ID {USLAR_ID}</script><h1>Ihr neues Zuhause</h1>",
    )
    with pytest.raises(ValueError, match="identify"):
        parse_kleinanzeigen_house_detail(html, url=USLAR_URL, expected_listing_id=USLAR_ID)


@pytest.mark.asyncio
async def test_opt_in_detail_enrichment_changes_typed_facts_not_seller_data(monkeypatch) -> None:
    import httpx

    from app.sources.base import RawProperty
    from app.sources.property.kleinanzeigen_de import KleinanzeigenGermanyPropertySource

    html = detail_html(
        plot="217 m²", description="Gasheizung aus 2010.", identity=USLAR_ID,
    )
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(
            200, request=request, text=html,
            headers={"content-type": "text/html; charset=UTF-8"},
        )

    source = KleinanzeigenGermanyPropertySource(detail_checks_per_shard=1)
    async def no_wait() -> None:
        return None
    monkeypatch.setattr(source, "_sleep", no_wait)
    item = RawProperty(source_listing_id=USLAR_ID, url=USLAR_URL, title="Uslar",
                       price_eur=Decimal(85000), raw_payload={"country_code": "DE"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        success = await source._enrich_public_detail(client, item)

    assert success is True
    assert requested == [USLAR_URL]
    assert item.plot_area_m2 == Decimal(217)
    assert item.raw_payload["heating_types"] == ["gas"]
    assert item.raw_payload["detail_enriched"] is True
    assert item.raw_payload["plot_area_source"] == "kleinanzeigen_detail"
    assert "description" not in item.raw_payload


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 503])
async def test_opt_in_detail_access_gate_halts_without_retry(monkeypatch, status: int) -> None:
    import httpx

    from app.sources.base import RawProperty, SourceFetchError
    from app.sources.property.kleinanzeigen_de import KleinanzeigenGermanyPropertySource

    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, request=request)

    source = KleinanzeigenGermanyPropertySource(detail_checks_per_shard=1)
    async def no_wait() -> None:
        return None
    monkeypatch.setattr(source, "_sleep", no_wait)
    item = RawProperty(source_listing_id=USLAR_ID, url=USLAR_URL, title="Uslar")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceFetchError) as exc:
            await source._enrich_public_detail(client, item)
    assert exc.value.halt_source is True
    assert len(calls) == 1


def test_detail_checks_cover_all_results_by_default_with_optional_diagnostic_cap() -> None:
    from app.sources.property.kleinanzeigen_de import KleinanzeigenGermanyPropertySource

    assert KleinanzeigenGermanyPropertySource().detail_checks_per_shard is None
    assert KleinanzeigenGermanyPropertySource(detail_checks_per_shard=0).detail_checks_per_shard == 0
    assert KleinanzeigenGermanyPropertySource(detail_checks_per_shard=9).detail_checks_per_shard == 9
    with pytest.raises(ValueError, match="non-negative"):
        KleinanzeigenGermanyPropertySource(detail_checks_per_shard=-1)


def test_manual_cli_has_no_terms_confirmation_gate(monkeypatch) -> None:
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    from types import SimpleNamespace

    file = Path(__file__).resolve().parents[1] / "scripts" / "run_kleinanzeigen_de.py"
    spec = spec_from_file_location("kleinanzeigen_detail_runner_test", file)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    args = SimpleNamespace(
        frontier_pages=12, hard_max_pages=40, delay=3.0,
        enable_regional_expansion=False, activate_regional_expansion_only=True,
        detail_checks_per_shard=None,
    )
    monkeypatch.setattr(module, "parse_args", lambda: args)
    monkeypatch.setattr(module, "get_or_create_source", lambda **_kwargs: 444)
    import asyncio
    assert asyncio.run(module.async_main()) == 0
