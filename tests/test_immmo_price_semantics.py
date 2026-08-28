from decimal import Decimal

from app.property_acquisition import property_budget_decision
from app.sources.property.immmo_v3 import parse_immmo_search_page


def test_price_on_request_does_not_promote_annual_income_to_purchase_price() -> None:
    html = """
    <html><body>
      <p>1 bis 12 von 1</p>
      <h3>Haus kaufen in 1180 Wien</h3>
      <a href="https://www.immobilienscout24.at/expose/67c8a150f7cc03fe08b41da9">
        RARITÄT | TOPLAGE NÄHE KUTSCHKERMARKT | ZWEI EXKLUSIVE DACHGESCHOSSWOHNUNGEN
      </a>
      <div>Preis auf Anfrage</div>
      <div>1180 Wien / 1.082m²</div>
      <div>Wohnfläche: 1.082 m² Nutzfläche: 1.082 m²</div>
      <div>Jahresertrag netto: € 45.243,72</div>
      <div>Kaufpreis auf Anfrage</div>
    </body></html>
    """

    page = parse_immmo_search_page(
        html,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Wien",
    )

    assert len(page.items) == 1
    item = page.items[0]
    assert item.price_eur is None
    assert item.raw_payload["price_semantics"] == "unknown"
    assert item.raw_payload["source_price_eur"] is None
    assert item.living_area_m2 == Decimal(1082)
    assert property_budget_decision(item.price_eur).reason == "price_unknown"


def test_numeric_search_summary_price_remains_authoritative() -> None:
    html = """
    <html><body>
      <p>1 bis 12 von 1</p>
      <h3>Haus kaufen in 8010 Graz</h3>
      <a href="https://example.test/house">Haus mit Garten</a>
      <div>€ 149.000,-</div>
      <div>8010 Graz / 120m²</div>
      <div>Jahresertrag netto: € 18.500,-</div>
    </body></html>
    """

    page = parse_immmo_search_page(
        html,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Steiermark",
    )

    item = page.items[0]
    assert item.price_eur == Decimal(149000)
    assert item.raw_payload["price_semantics"] == "summary_numeric"
    assert item.raw_payload["source_price_eur"] == "149000"
    assert property_budget_decision(item.price_eur).accepted is True


def test_purchase_price_wins_over_later_investment_amounts() -> None:
    html = """
    <html><body>
      <p>1 bis 12 von 1</p>
      <h3>Haus kaufen in 1160 Wien</h3>
      <a href="https://www.immobilienscout24.at/expose/6579d6eabfd5ce3bcce77d0a">
        KAPITALANLAGE DER BESONDEREN ART - Mitten in Wien
      </a>
      <div>€ 229.000,-</div>
      <div>1160 Wien / 96m²</div>
      <div>Jahresertrag / Investitionskennzahl: € 95.936,-</div>
      <div>Provision 3,6 %</div>
    </body></html>
    """

    page = parse_immmo_search_page(
        html,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Wien",
    )

    item = page.items[0]
    assert item.price_eur == Decimal(229000)
    assert item.raw_payload["price_semantics"] == "summary_numeric"
    assert item.raw_payload["source_price_eur"] == "229000"
    assert item.raw_payload["display_area_m2"] == "96"
