from decimal import Decimal

from app.sources.property.immmo_v2 import parse_immmo_search_page

FIXTURE = """
<html><body>
<p>1 bis 12 von 24</p>
<ul>
<li>
  <h3>Haus kaufen in 3950 Gmünd</h3>
  <div><a href="https://portal.example/object/1">Charmantes Haus mit Garten</a></div>
  <div>€ 249.000,-</div>
  <div>3950 Gmünd / 132,66m² / 6 Zimmer</div>
  <p>Grundstücksfläche von ca. 368 m².</p>
  <div><a href="https://portal.example/object/1">Mehr</a></div>
</li>
<li>
  <h3>Haus kaufen in 2722 Winzendorf</h3>
  <div><a href="https://other.example/2">Doppelhaushälfte schlüsselfertig</a></div>
  <div>€ 320.000,-</div>
  <div>2722 Winzendorf / 100m² / 5 Zimmer</div>
  <p>Rund 410 m² Grundstück bieten Platz.</p>
</li>
</ul>
</body></html>
"""

DUPLICATE_URL_FIXTURE = """
<html><body>
<p>1 bis 12 von 2</p>
<h3>Haus kaufen in 8010 Graz</h3>
<a href="https://portal.example/same">Haus A</a>
<div>€ 300.000,-</div>
<div>8010 Graz / 90m² / 4 Zimmer</div>
<h3>Haus kaufen in 8020 Graz</h3>
<a href="https://portal.example/same">Haus A auch hier gelistet</a>
<div>€ 300.000,-</div>
<div>8020 Graz / 90m² / 4 Zimmer</div>
</body></html>
"""


def test_stream_parser_keeps_location_and_area_with_nested_links() -> None:
    page = parse_immmo_search_page(
        FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Niederoesterreich",
    )

    assert page.reported_count == 24
    assert page.cards_seen == 2
    assert len(page.items) == 2

    first = next(item for item in page.items if item.url.endswith("/object/1"))
    assert first.title == "Charmantes Haus mit Garten"
    assert first.price_eur == Decimal(249000)
    assert first.postal_code == "3950"
    assert first.city == "Gmünd"
    assert first.living_area_m2 == Decimal("132.66")
    assert first.plot_area_m2 == Decimal(368)

    second = next(item for item in page.items if item.url.endswith("/2"))
    assert second.price_eur == Decimal(320000)
    assert second.postal_code == "2722"
    assert second.city == "Winzendorf"
    assert second.living_area_m2 == Decimal(100)
    assert second.plot_area_m2 == Decimal(410)


def test_stream_parser_deduplicates_repeated_links_inside_one_card() -> None:
    page = parse_immmo_search_page(
        FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Niederoesterreich",
    )
    assert len([item for item in page.items if item.url.endswith("/object/1")]) == 1
    assert page.cards_seen == 2


def test_card_count_is_independent_from_unique_original_urls() -> None:
    page = parse_immmo_search_page(
        DUPLICATE_URL_FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Steiermark",
    )

    assert page.reported_count == 2
    assert page.cards_seen == 2
    assert len(page.items) == 1
