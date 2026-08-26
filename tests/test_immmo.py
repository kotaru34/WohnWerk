from decimal import Decimal

from app.sources.property.immmo import parse_immmo_search_page


SEARCH_FIXTURE = """
<html><body>
<h1>Häuser zu kaufen in Niederösterreich</h1>
<p>1 bis 12 von 24</p>
<header><a href="https://www.facebook.com/immmo">Facebook</a></header>
<article>
  <h3>Haus kaufen in 3950 Gmünd</h3>
  <a href="https://www.example-immo.at/object/abc123?x=1">
    Familienglück in Gmünd – 132 m² Wohnfläche mit eigenem Garten
  </a>
  <div>€ 249.000,-</div>
  <div>3950 Gmünd / 132,66m² / 6 Zimmer</div>
  <p>Das Wohnhaus steht auf einer Grundstücksfläche von ca. 368 m².</p>
  <a href="https://www.example-immo.at/object/abc123?x=1">Mehr</a>
</article>
<article>
  <h3>Haus kaufen in 2722 Winzendorf</h3>
  <a href="https://portal.example/listing/987">Doppelhaushälfte schlüsselfertig</a>
  <div>€ 320.000,-</div>
  <div>2722 Winzendorf / 100m² / 5 Zimmer</div>
  <p>Rund 410 m² Grundstück bieten Platz für die Familie.</p>
</article>
<a href="/immo/Haus-kaufen/Niederoesterreich/2">2</a>
</body></html>
"""

LOWER_BOUND_FIXTURE = """
<html><body>
<p>1 bis 12 von mehr als 12000</p>
<article>
  <a href="https://portal.example/listing/1">Haus mit Garten</a>
  <div>€ 199.000,-</div>
  <div>8010 Graz / 90m² / 4 Zimmer</div>
</article>
</body></html>
"""


def test_immmo_parser_extracts_minimal_original_listing_metadata() -> None:
    page = parse_immmo_search_page(
        SEARCH_FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Niederoesterreich",
    )

    assert page.reported_count == 24
    assert page.count_is_lower_bound is False
    assert len(page.items) == 2

    first = page.items[0]
    assert first.url == "https://www.example-immo.at/object/abc123?x=1"
    assert first.title == "Familienglück in Gmünd – 132 m² Wohnfläche mit eigenem Garten"
    assert first.price_eur == Decimal(249000)
    assert first.living_area_m2 == Decimal("132.66")
    assert first.plot_area_m2 == Decimal(368)
    assert first.postal_code == "3950"
    assert first.city == "Gmünd"
    assert first.description is None
    assert first.raw_payload["original_host"] == "www.example-immo.at"

    second = page.items[1]
    assert second.price_eur == Decimal(320000)
    assert second.living_area_m2 == Decimal(100)
    assert second.plot_area_m2 == Decimal(410)
    assert second.postal_code == "2722"
    assert second.city == "Winzendorf"


def test_immmo_parser_deduplicates_repeated_links_for_one_card() -> None:
    page = parse_immmo_search_page(
        SEARCH_FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Niederoesterreich",
    )
    assert len([item for item in page.items if "abc123" in item.url]) == 1


def test_immmo_parser_marks_more_than_count_as_lower_bound() -> None:
    page = parse_immmo_search_page(
        LOWER_BOUND_FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Oesterreich",
    )
    assert page.reported_count == 12000
    assert page.count_is_lower_bound is True
    assert len(page.items) == 1
