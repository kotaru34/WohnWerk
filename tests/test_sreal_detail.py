from decimal import Decimal

from app.sources.base import RawProperty
from app.sources.property.sreal_detail import enrich_sreal_property, parse_sreal_detail_page

DETAIL_FIXTURE = """
<html><head>
<meta property="og:image" content="/media/immobilien/964-31642-main.jpg">
</head><body>
<h3>Preis-Hit mit viel Platz – Zwei Häuser auf einem Grundstück</h3>
<div>4372 St. Georgen am Walde - 964/31642</div>
<ul>
  <li>Wohnfläche 310 m<sup>2</sup></li>
  <li>Grundfläche 1.649 m²</li>
  <li>Kaufpreis 573.000,00 €</li>
</ul>
<h3>Objektbeschreibung</h3>
<p>Diese außergewöhnliche Liegenschaft vereint großzügiges Wohnen und flexible Nutzung.</p>
<p>Auf dem Grundstück befinden sich zwei eigenständige Wohnhäuser.</p>
<h4>Frau Beispiel Maklerin</h4>
<p>Kontakttext darf nicht Teil der Beschreibung werden.</p>
<h3>Infrastruktur</h3>
</body></html>
"""

EXPECTED_IMAGE_URL = "https://www.sreal.at/media/immobilien/964-31642-main.jpg"


def test_sreal_detail_parser_extracts_full_property_metadata() -> None:
    detail = parse_sreal_detail_page(
        DETAIL_FIXTURE,
        page_url=(
            "https://www.sreal.at/de/immobilie/964-31642/"
            "preis-hit-mit-viel-platz"
        ),
    )

    assert detail.listing_id == "964-31642"
    assert detail.postal_code == "4372"
    assert detail.city == "St. Georgen am Walde"
    assert detail.living_area_m2 == Decimal(310)
    assert detail.plot_area_m2 == Decimal(1649)
    assert detail.price_eur == Decimal("573000.00")
    assert detail.description is not None
    assert "außergewöhnliche Liegenschaft" in detail.description
    assert "Kontakttext" not in detail.description
    assert detail.primary_image_url == EXPECTED_IMAGE_URL


def test_sreal_detail_enrichment_preserves_card_fallbacks() -> None:
    card = RawProperty(
        source_listing_id="964-31642",
        url="https://www.sreal.at/de/immobilie/964-31642/preis-hit-mit-viel-platz",
        title="Preis-Hit mit viel Platz",
        price_eur=Decimal(570000),
        living_area_m2=Decimal(310),
        postal_code="4372",
        city="St. Georgen am Walde",
        raw_payload={"format": "sreal-search-discovery-v2", "identity_stable": True},
    )
    detail = parse_sreal_detail_page(DETAIL_FIXTURE, page_url=card.url)
    enriched = enrich_sreal_property(card, detail)

    assert enriched.price_eur == Decimal("573000.00")
    assert enriched.living_area_m2 == Decimal(310)
    assert enriched.plot_area_m2 == Decimal(1649)
    assert enriched.description is not None
    assert enriched.raw_payload["detail_enriched"] is True
    assert enriched.raw_payload["primary_image_url"] == EXPECTED_IMAGE_URL
