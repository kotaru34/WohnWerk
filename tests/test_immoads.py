from decimal import Decimal

from app.sources.property.immoads import parse_immoads_detail, parse_immoads_search_page

SEARCH_FIXTURE = """
<html><body>
<h1>Haus kaufen in Österreich</h1>
<p>Es wurden 751 Objekte gefunden</p>
<a href="/immobilien/haus-kaufen/wien/wien-23-liesing/1230-wien/01147790-einfamilienhaus-am-rosenhuegel">
  Einfamilienhaus mit hochwertiger Ausstattung am Rosenhügel
</a>
<a href="/immobilien/haus-kaufen/niederoesterreich/mistelbach/2120-wolkersdorf/01158413-grosses-wohnhaus">
  Großes Wohnhaus
</a>
<a href="?order=latest&page=2">2</a>
<a href="?order=latest&page=76">76</a>
</body></html>
"""

DETAIL_FIXTURE = """
<html><body>
<h1>Einfamilienhaus mit hochwertiger Ausstattung am Rosenhügel</h1>
<h2>Einfamilienhaus kaufen in 1230 Wien,Liesing, Wien</h2>
<h3>Eckdaten</h3>
<div>Kaufpreis</div><div>€ 1.200.000,00</div>
<div>Fläche</div><div>168,05 m²</div>
<div>Zimmer</div><div>6</div>
<div>PLZ</div><div>1230</div>
<div>Ort</div><div>Wien,Liesing</div>
<h3>Beschreibung &amp; Informationen</h3>
<p>Schönes Familienhaus in ruhiger Lage.</p>
<p>Weitere Informationen zum Objekt.</p>
<div>Objekt-Nr. 1147790</div>
<h3>Merkmale</h3>
<div>Wohnfläche m²</div><div>168,05 m²</div>
<div>Grundstücksfläche m²</div><div>460 m²</div>
</body></html>
"""

DETAIL_DESCRIPTION_AREA_FIXTURE = """
<html><body>
<h1>Landhaus mit großem Grundstück</h1>
<div>Kaufpreis</div><div>€ 695.000,00</div>
<div>Fläche</div><div>900 m²</div>
<div>PLZ</div><div>8522</div>
<div>Ort</div><div>Kraubath</div>
<h3>Beschreibung &amp; Informationen</h3>
<p>Auf rund 19.200 m² Grundstücksfläche entfaltet sich ein weitläufiges Ensemble.</p>
<div>Objekt-Nr. 1124037</div>
</body></html>
"""


def test_search_parser_extracts_unique_listing_refs_and_page_count() -> None:
    refs, count, max_page = parse_immoads_search_page(
        SEARCH_FIXTURE,
        page_url="https://www.immoads.at/immobilien/haus-kaufen?order=latest&page=1",
    )

    assert count == 751
    assert max_page == 76
    assert [ref.source_listing_id for ref in refs] == ["1147790", "1158413"]
    assert refs[0].url.startswith("https://www.immoads.at/immobilien/haus-kaufen/")


def test_detail_parser_extracts_core_house_fields() -> None:
    record = parse_immoads_detail(
        DETAIL_FIXTURE,
        url="https://www.immoads.at/immobilien/haus-kaufen/example/01147790-example",
        source_listing_id="1147790",
    )

    assert record is not None
    assert record.title == "Einfamilienhaus mit hochwertiger Ausstattung am Rosenhügel"
    assert record.price_eur == Decimal("1200000.00")
    assert record.living_area_m2 == Decimal("168.05")
    assert record.plot_area_m2 == Decimal(460)
    assert record.postal_code == "1230"
    assert record.city == "Wien,Liesing"
    assert "Schönes Familienhaus" in (record.description or "")


def test_detail_parser_can_recover_plot_area_from_description() -> None:
    record = parse_immoads_detail(
        DETAIL_DESCRIPTION_AREA_FIXTURE,
        url="https://www.immoads.at/immobilien/haus-kaufen/example/01124037-example",
        source_listing_id="1124037",
    )

    assert record is not None
    assert record.plot_area_m2 == Decimal(19200)


def test_removed_or_sold_pages_are_not_ingested() -> None:
    removed = parse_immoads_detail(
        "<html><body><h1>Seite existiert nicht mehr</h1></body></html>",
        url="https://www.immoads.at/removed",
        source_listing_id="1",
    )
    sold = parse_immoads_detail(
        "<html><body><h1>VERKAUFT - Haus</h1><div>PLZ</div><div>4020</div></body></html>",
        url="https://www.immoads.at/sold",
        source_listing_id="2",
    )

    assert removed is None
    assert sold is None
