from decimal import Decimal

from app.sources.property.openimmo import parse_openimmo_properties


OPENIMMO_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<openimmo>
  <anbieter>
    <immobilie>
      <objektkategorie>
        <vermarktungsart KAUF="true" MIETE_PACHT="false" />
        <objektart><haus haustyp="EINFAMILIENHAUS" /></objektart>
      </objektkategorie>
      <geo><plz>4020</plz><ort>Linz</ort></geo>
      <preise><kaufpreis>485000.00</kaufpreis></preise>
      <flaechen>
        <wohnflaeche>142.5</wohnflaeche>
        <grundstuecksflaeche>680</grundstuecksflaeche>
      </flaechen>
      <freitexte>
        <objekttitel>Haus mit Garten</objekttitel>
        <objektbeschreibung>Beschreibung</objektbeschreibung>
        <lage>Ruhige Lage</lage>
      </freitexte>
      <verwaltung_techn><objektnr_extern>AT-123</objektnr_extern></verwaltung_techn>
    </immobilie>
    <immobilie>
      <objektkategorie>
        <vermarktungsart KAUF="false" MIETE_PACHT="true" />
        <objektart><haus haustyp="REIHENHAUS" /></objektart>
      </objektkategorie>
      <verwaltung_techn><objektnr_extern>AT-RENT</objektnr_extern></verwaltung_techn>
    </immobilie>
    <immobilie>
      <objektkategorie>
        <vermarktungsart KAUF="true" />
        <objektart><wohnung wohnungtyp="ETAGE" /></objektart>
      </objektkategorie>
      <verwaltung_techn><objektnr_extern>AT-FLAT</objektnr_extern></verwaltung_techn>
    </immobilie>
  </anbieter>
</openimmo>
"""


def test_parser_keeps_only_houses_for_sale() -> None:
    records = parse_openimmo_properties(OPENIMMO_FIXTURE, fallback_url="https://example.at/feed.xml")

    assert len(records) == 1
    record = records[0]
    assert record.source_listing_id == "AT-123"
    assert record.title == "Haus mit Garten"
    assert record.postal_code == "4020"
    assert record.city == "Linz"
    assert record.price_eur == Decimal("485000.00")
    assert record.living_area_m2 == Decimal("142.5")
    assert record.plot_area_m2 == Decimal("680")
    assert record.description == "Beschreibung\n\nRuhige Lage"
    assert record.raw_payload["house_type"] == "EINFAMILIENHAUS"
