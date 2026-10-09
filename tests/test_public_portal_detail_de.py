"""Real-site-shaped, offline contracts for German public house detail verification."""

from decimal import Decimal

from app.sources.property.public_portal_detail_de import verify_public_house_detail


def _immobilien_detail(
    *, listing_id: str = "9794876", price: str = "139.000 €Kaufpreis",
    extra: str = "",
) -> str:
    return (
        "<main><h1>Doppelhaushälfte mit Keller in Neubrandenburg</h1>"
        "<p>17034 Neubrandenburg</p>"
        f"<p>{price}</p><p>Wohnfläche 96 m²</p>"
        "<p>Grundstücksfläche 650 m²</p><p>Baujahr 1936</p>"
        f"<p>immobilien.de Nr.{listing_id} Obj.-Nr.{listing_id}</p>"
        f"<p>{extra}</p></main>"
    )


def _verify(html: str, provider: str = "immobilien-de"):
    return verify_public_house_detail(
        html, provider_name=provider, listing_id="9794876",
        price_eur=Decimal("139000"), postal_code="17034",
    )


def test_existing_house_with_actual_land_and_year_is_verified() -> None:
    result = _verify(_immobilien_detail())
    assert result.verified is True
    assert result.reason == "verified_existing_house"


def test_missing_listing_id_or_mismatched_ask_is_not_accepted() -> None:
    assert _verify(_immobilien_detail(listing_id="10043535")).reason == (
        "listing_id_unverified"
    )
    assert _verify(_immobilien_detail(price="999 €Kaufpreis")).reason == (
        "asking_price_unverified"
    )


def test_construction_price_excluding_land_is_rejected() -> None:
    content = _immobilien_detail(
        extra="Ein Auszug aus der Bauleistungsbeschreibung. "
        "Die Kosten für Grundstück und Außenanlagen übernimmt der Auftraggeber."
    )
    result = _verify(content)
    assert result.verified is False
    assert result.reason == "construction_only"


def test_without_maekler_real_existing_home_is_verified() -> None:
    html = (
        "<main><h1>Einfamilienhaus mit Garten</h1>"
        "<p>17213 Fünfseen</p><p>Kaufpreis | 120.000 €</p>"
        "<p>Wohnfläche 145 m², Grundstücksfläche 800 m²</p>"
        "<p>Objekt-Nr | OM-503161</p><p>Baujahr | 1980</p></main>"
    )
    evidence = verify_public_house_detail(
        html,
        provider_name="ohne-makler-de",
        listing_id="503161",
        price_eur=Decimal(120000),
        postal_code="17213",
    )
    assert evidence.verified is True


def test_holiday_home_without_primary_residence_is_excluded() -> None:
    html = _immobilien_detail(extra="Ferienhaus, nicht Hauptwohnsitz möglich")
    evidence = _verify(html)
    assert evidence.reason == "no_primary_residence"


def test_no_real_plot_or_year_is_not_an_existing_house_verification() -> None:
    missing_plot = (
        "<main><p>immobilien.de Nr.9794876</p><p>17034 Neubrandenburg</p>"
        "<p>139.000 €Kaufpreis</p><p>Wohnfläche 96 m² Baujahr 1936</p></main>"
    )
    assert _verify(missing_plot).reason == "land_area_unverified"
    missing_year = (
        "<main><p>immobilien.de Nr.9794876</p><p>17034 Neubrandenburg</p>"
        "<p>139.000 €Kaufpreis</p>"
        "<p>Wohnfläche 96 m² Grundstücksfläche 650 m²</p></main>"
    )
    assert _verify(missing_year).reason == "existing_building_unverified"
