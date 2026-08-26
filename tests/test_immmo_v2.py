from decimal import Decimal

from app.sources.property.immmo_v2 import parse_immmo_search_page

FIXTURE = """
<html><body>
<p>1 bis 12 von 24</p>
<ul>
<li>
  <div>Haus kaufen in 3950 Gmünd</div>
  <div><a href="https://portal.example/object/1">Charmantes Haus mit Garten</a></div>
  <div>€ 249.000,-</div>
  <div>3950 Gmünd / 132,66m² / 6 Zimmer</div>
  <p>Grundstücksfläche von ca. 368 m².</p>
  <div><a href="https://portal.example/object/1">Mehr</a></div>
</li>
<li>
  <div>Haus kaufen in 2722 Winzendorf</div>
  <div><a href="https://other.example/2">Doppelhaushälfte schlüsselfertig</a></div>
  <div>€ 320.000,-</div>
  <div>2722 Winzendorf / 100m² / 5 Zimmer</div>
  <p>Rund 410 m² Grundstück bieten Platz.</p>
</li>
<li>
  <div>Haus kaufen in 7202 Bad Sauerbrunn</div>
  <a href="https://third.example/3">Sommerrefugium direkt am See</a>
  <div>€ 178.000,-</div>
  <div>7202 Bad Sauerbrunn</div>
  <p>Das Grundstück hat 150 m²; eine Wohnfläche wird im Snippet nicht genannt.</p>
</li>
</ul>
</body></html>
"""


def test_stream_parser_keeps_location_area_and_title_without_dom_card_assumptions() -> None:
    page = parse_immmo_search_page(
        FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Niederoesterreich",
    )

    assert page.reported_count == 24
    assert len(page.items) == 3

    first = next(item for item in page.items if item.url.endswith("/object/1"))
    assert first.title == "Charmantes Haus mit Garten"
    assert first.price_eur == Decimal(249000)
    assert first.postal_code == "3950"
    assert first.city == "Gmünd"
    assert first.living_area_m2 == Decimal("132.66")
    assert first.plot_area_m2 == Decimal(368)
    assert first.raw_payload["source_postal_code"] == "3950"

    second = next(item for item in page.items if item.url.endswith("/2"))
    assert second.price_eur == Decimal(320000)
    assert second.postal_code == "2722"
    assert second.city == "Winzendorf"
    assert second.living_area_m2 == Decimal(100)
    assert second.plot_area_m2 == Decimal(410)


def test_stream_parser_uses_heading_plz_when_summary_has_no_living_area() -> None:
    page = parse_immmo_search_page(
        FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Burgenland",
    )
    third = next(item for item in page.items if item.url.endswith("/3"))
    assert third.postal_code == "7202"
    assert third.city == "Bad Sauerbrunn"
    assert third.living_area_m2 is None
    assert third.price_eur == Decimal(178000)


def test_stream_parser_ignores_repeated_non_title_external_links() -> None:
    page = parse_immmo_search_page(
        FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Niederoesterreich",
    )
    assert len([item for item in page.items if item.url.endswith("/object/1")]) == 1
