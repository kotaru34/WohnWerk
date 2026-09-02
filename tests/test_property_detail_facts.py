from decimal import Decimal

from app.property_detail_enrichment import _detail_title_is_safe_upgrade
from app.property_detail_facts import (
    extract_findmyhome_property_facts,
    extract_immoscout_property_facts,
    extract_property_detail_facts,
    immoscout_facts_match_listing,
    property_facts_match_listing,
)


def test_extracts_immoscout_price_and_plot_area() -> None:
    body = '''{
      "obj_objectnumber":"6a91ab98c69313e56d51e832",
      "obj_title":"Einfamilienhaus in ruhiger Lage mit Modernisierungsbedarf in Fohnsdorf",
      "obj_zipCode":"8753",
      "obj_purchasePrice":"169000",
      "obj_livingSpace":"83.38",
      "obj_usableArea":"83.38",
      "obj_lotArea":"785"
    }'''

    facts = extract_immoscout_property_facts(
        "https://www.immobilienscout24.at/expose/6a91ab98c69313e56d51e832",
        body,
    )

    assert facts is not None
    assert facts.purchase_price_eur == Decimal(169000)
    assert facts.living_area_m2 == Decimal("83.38")
    assert facts.usable_area_m2 == Decimal("83.38")
    assert facts.plot_area_m2 == Decimal(785)
    assert facts.postal_code == "8753"
    assert immoscout_facts_match_listing(
        facts,
        listing_url="https://www.immobilienscout24.at/expose/6a91ab98c69313e56d51e832",
        postal_code="8753",
        title="Einfamilienhaus in ruhiger Lage mit Modernisierungsbedarf in Fohnsdorf",
    )


def test_extracts_immoscout_graphql_area_semantics() -> None:
    body = '''{
      "unrelated":{"livingArea":999,"effectiveArea":888,"plotArea":777},
      "area":{
        "__typename":"Area",
        "primaryArea":83.38,
        "livingArea":null,
        "balconyArea":null,
        "cellarArea":null,
        "gardenArea":null,
        "plotArea":785,
        "totalArea":null,
        "outdoorSpaces":[],
        "numberOfRooms":4,
        "effectiveArea":83.38
      },
      "targeting":{
        "obj_zipCode":"8753",
        "obj_title":"Einfamilienhaus in ruhiger Lage mit Modernisierungsbedarf in Fohnsdorf",
        "obj_purchasePrice":169000
      }
    }'''

    facts = extract_immoscout_property_facts(
        "https://www.immobilienscout24.at/expose/6a91ab98c69313e56d51e832",
        body,
    )

    assert facts is not None
    assert facts.purchase_price_eur == Decimal(169000)
    assert facts.living_area_m2 is None
    assert facts.usable_area_m2 == Decimal("83.38")
    assert facts.plot_area_m2 == Decimal(785)
    assert facts.postal_code == "8753"


def test_graphql_living_area_stays_distinct_from_effective_area() -> None:
    body = '''{
      "area":{
        "__typename":"Area",
        "primaryArea":121.5,
        "livingArea":96.4,
        "plotArea":510,
        "effectiveArea":121.5
      },
      "targeting":{
        "obj_zipCode":"6890",
        "obj_title":"Reihenhaus - bis zu € 100.000,- Wohnbauförderung möglich",
        "obj_purchasePrice":573500
      }
    }'''

    facts = extract_immoscout_property_facts(
        "https://www.immobilienscout24.at/expose/6579d6eabfd5ce3bcce77d0a",
        body,
    )

    assert facts is not None
    assert facts.living_area_m2 == Decimal("96.4")
    assert facts.usable_area_m2 == Decimal("121.5")
    assert facts.plot_area_m2 == Decimal(510)


def test_title_promotion_amount_does_not_replace_purchase_price_metadata() -> None:
    body = '''{
      "obj_title":"Reihenhaus - bis zu € 100.000,- Wohnbauförderung möglich",
      "obj_zipCode":"6890",
      "obj_purchasePrice":573500,
      "obj_livingSpace":96.4
    }'''

    facts = extract_immoscout_property_facts(
        "https://www.immobilienscout24.at/expose/6579d6eabfd5ce3bcce77d0a",
        body,
    )

    assert facts is not None
    assert facts.purchase_price_eur == Decimal(573500)
    assert facts.living_area_m2 == Decimal("96.4")
    assert immoscout_facts_match_listing(
        facts,
        listing_url="https://www.immobilienscout24.at/expose/6579d6eabfd5ce3bcce77d0a",
        postal_code="6890",
        title="Reihenhaus - bis zu",
    )


def test_immoscout_primary_image_comes_from_provider_metadata() -> None:
    body = '''
      <html><head>
        <meta property="og:image" content="https://pictures.example/correct-house.jpg">
      </head><body>
        <script>{"obj_zipCode":"4464","obj_title":"1- bis 2-Familienhaus mit Terrasse und Nebengebäude","obj_purchasePrice":133000}</script>
      </body></html>
    '''

    facts = extract_property_detail_facts(
        "https://www.immobilienscout24.at/expose/6a8d788a1395c71377689b4f",
        body,
    )

    assert facts is not None
    assert facts.primary_image_url == "https://pictures.example/correct-house.jpg"


def test_findmyhome_house_summary_area_and_ground_area_are_explicit_semantics() -> None:
    body = '''
      <html><head><meta property="og:image" content="/media/5657040.jpg"></head><body>
        <h1>Gepflegtes Landhaus mit Carport, Nebengebäude, Garten und uneinsehbarem Innenhof - Objektnr. 5657040</h1>
        <div>3762 Ort € 119.000,00 Kaufpreis 91,00 m² Fläche</div>
        <section>ECKDATEN FindMyHome.at // Externe Immobilien-ID 5657040 // 960/74421
          Immobilienart Haus - Eigentum Anschrift 3762 Ludweis-Aigen
          Grundfläche 653,00 m² Kaufpreis: € 119.000,00
        </section>
      </body></html>
    '''

    facts = extract_findmyhome_property_facts("https://www.findmyhome.at/5657040", body)

    assert facts is not None
    assert facts.purchase_price_eur == Decimal("119000.00")
    assert facts.living_area_m2 == Decimal("91.00")
    assert facts.plot_area_m2 == Decimal("653.00")
    assert facts.postal_code == "3762"
    assert facts.object_number == "5657040"
    assert facts.title == (
        "Gepflegtes Landhaus mit Carport, Nebengebäude, Garten und uneinsehbarem Innenhof"
    )
    assert facts.primary_image_url == "https://www.findmyhome.at/media/5657040.jpg"
    assert property_facts_match_listing(
        facts,
        listing_url="https://www.findmyhome.at/5657040",
        postal_code="3762",
        title="Gepflegtes Landhaus mit Carport, Nebengebäude, Garten und uneinsehbarem Innenhof",
    )


def test_findmyhome_second_example_extracts_566_square_metre_plot() -> None:
    body = '''
      <html><body>
        <h1>Landleben genießen: Einfamilienhaus mit Garten und Doppelgarage - Objektnr. 5640125</h1>
        <div>€ 187.000,00 Kaufpreis 90,00 m² Fläche 3.0 Zimmer</div>
        <div>Immobilienart Haus - Eigentum Anschrift 2164 Wildendürnbach
             Grundfläche 566,00 m² Kaufpreis: € 187.000,00</div>
      </body></html>
    '''

    facts = extract_property_detail_facts("https://www.findmyhome.at/5640125", body)

    assert facts is not None
    assert facts.living_area_m2 == Decimal("90.00")
    assert facts.plot_area_m2 == Decimal("566.00")
    assert facts.postal_code == "2164"


def test_findmyhome_does_not_guess_generic_flat_area_as_house_living_area() -> None:
    body = '''
      <html><body><h1>Wohnung - Objektnr. 1234567</h1>
      <div>91,00 m² Fläche Immobilienart Wohnung - Eigentum</div></body></html>
    '''

    assert extract_findmyhome_property_facts("https://www.findmyhome.at/1234567", body) is None


def test_detail_title_can_only_extend_existing_title() -> None:
    assert _detail_title_is_safe_upgrade(
        "Reihenhaus - bis zu",
        "Reihenhaus - bis zu € 100.000,- Wohnbauförderung möglich",
    )
    assert not _detail_title_is_safe_upgrade(
        "Reihenhaus - bis zu",
        "Völlig anderes Haus in einer anderen Stadt",
    )
    assert not _detail_title_is_safe_upgrade(
        "Vollständiger Titel",
        "Vollständiger Titel",
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
