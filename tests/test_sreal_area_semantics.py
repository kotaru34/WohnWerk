from decimal import Decimal

from app.sources.property.sreal_detail import parse_sreal_detail_page


def _parse(body: str):
    html = f"<html><body>{body}</body></html>"
    return parse_sreal_detail_page(
        html,
        page_url=(
            "https://www.sreal.at/de/immobilie/964-31638/"
            "wohnhaus-mit-viel-potenzial"
        ),
    )


def test_sreal_uses_value_before_wohnflaeche_and_keeps_nutzflaeche() -> None:
    detail = _parse(
        """
        <div>4941 Mehrnbach - 964/31638</div>
        <div>Grundfläche 1.106 m²</div>
        <div>Nutzfläche 140 m²</div>
        <div>Kaufpreis 349.000,00 €</div>
        <h3>Objektbeschreibung</h3>
        <p>Das Haus verfügt über ca. 140 m² Wohnfläche und einen großen Keller.</p>
        <h3>Merkmale</h3>
        """
    )

    assert detail.postal_code == "4941"
    assert detail.city == "Mehrnbach"
    assert detail.price_eur == Decimal("349000.00")
    assert detail.living_area_m2 == Decimal("140")
    assert detail.usable_area_m2 == Decimal("140")
    assert detail.plot_area_m2 == Decimal("1106")


def test_sreal_accepts_wohnnutzflaeche_spelling_variants() -> None:
    for label in (
        "Wohnnutzfläche",
        "Wohn-Nutzfläche",
        "Wohn/Nutzfläche",
        "Wohn-/Nutzfläche",
    ):
        detail = _parse(
            f"""
            <div>4941 Mehrnbach - 964/31638</div>
            <div>{label}: ca. 125,5 m²</div>
            <div>Grundstücksfläche ca. 650 m²</div>
            <div>Kaufpreis 120.000 €</div>
            """
        )
        assert detail.living_area_m2 == Decimal("125.5")
        assert detail.plot_area_m2 == Decimal("650")


def test_sreal_keeps_generic_nutzflaeche_without_renaming_it_wohnflaeche() -> None:
    detail = _parse(
        """
        <div>4941 Mehrnbach - 964/31638</div>
        <div>Nutzfläche: 180 m²</div>
        <div>Grundstück: 900 m²</div>
        <div>Kaufpreis 130.000 €</div>
        """
    )

    assert detail.living_area_m2 is None
    assert detail.usable_area_m2 == Decimal("180")
    assert detail.plot_area_m2 == Decimal("900")


def test_sreal_area_fields_do_not_cross_bind_flattened_metadata() -> None:
    detail = _parse(
        """
        <div>4941 Mehrnbach - 964/31638</div>
        <div>Nutzfläche: 120 m² Grundstücksfläche: 784 m²</div>
        <div>Kaufpreis 140.000 €</div>
        """
    )

    assert detail.living_area_m2 is None
    assert detail.usable_area_m2 == Decimal("120")
    assert detail.plot_area_m2 == Decimal("784")
