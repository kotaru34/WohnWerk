from decimal import Decimal

from app.property_detail_facts import (
    extract_immoscout_property_facts,
    immoscout_facts_match_listing,
)


def test_extracts_immoscout_price_and_plot_area() -> None:
    body = '''{
      "obj_objectnumber":"6a91ab98c69313e56d51e832",
      "obj_title":"Einfamilienhaus in ruhiger Lage mit Modernisierungsbedarf in Fohnsdorf",
      "obj_zipCode":"8753",
      "obj_purchasePrice":"169000",
      "obj_livingSpace":"83.38",
      "obj_lotArea":"785"
    }'''

    facts = extract_immoscout_property_facts(
        "https://www.immobilienscout24.at/expose/6a91ab98c69313e56d51e832",
        body,
    )

    assert facts is not None
    assert facts.purchase_price_eur == Decimal(169000)
    assert facts.living_area_m2 == Decimal("83.38")
    assert facts.plot_area_m2 == Decimal(785)
    assert facts.postal_code == "8753"
    assert immoscout_facts_match_listing(
        facts,
        listing_url="https://www.immobilienscout24.at/expose/6a91ab98c69313e56d51e832",
        postal_code="8753",
        title="Einfamilienhaus in ruhiger Lage mit Modernisierungsbedarf in Fohnsdorf",
    )


def test_title_promotion_amount_does_not_replace_purchase_price_metadata() -> None:
    body = '''{
      "obj_title":"Reihenhaus - bis zu € 100.000,- Wohnbauförderung möglich",
      "obj_zipCode":"6890",
      "obj_purchasePrice":573500
    }'''

    facts = extract_immoscout_property_facts(
        "https://www.immobilienscout24.at/expose/6579d6eabfd5ce3bcce77d0a",
        body,
    )

    assert facts is not None
    assert facts.purchase_price_eur == Decimal(573500)
    assert immoscout_facts_match_listing(
        facts,
        listing_url="https://www.immobilienscout24.at/expose/6579d6eabfd5ce3bcce77d0a",
        postal_code="6890",
        title="Reihenhaus - bis zu € 100.000,- Wohnbauförderung möglich",
    )


def test_rejects_historical_cross_card_identity_mismatch() -> None:
    body = '''{
      "obj_objectnumber":"other-id",
      "obj_title":"Anderes Haus",
      "obj_zipCode":"6890",
      "obj_purchasePrice":573500,
      "obj_lotArea":500
    }'''
    facts = extract_immoscout_property_facts(
        "https://www.immobilienscout24.at/expose/6a91ab98c69313e56d51e832",
        body,
    )

    assert facts is not None
    assert not immoscout_facts_match_listing(
        facts,
        listing_url="https://www.immobilienscout24.at/expose/6a91ab98c69313e56d51e832",
        postal_code="8753",
        title="Einfamilienhaus in Fohnsdorf",
    )
