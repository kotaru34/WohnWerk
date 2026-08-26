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
  <h3>Doppelhaushälfte kaufen in 2722 Winzendorf</h3>
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
<h3>Einfamilienhaus kaufen in 8020 Graz</h3>
<a href="https://portal.example/same">Haus A auch hier gelistet</a>
<div>€ 300.000,-</div>
<div>8020 Graz / 90m² / 4 Zimmer</div>
</body></html>
"""

PROSE_HEADING_FIXTURE = """
<html><body>
<p>1 bis 12 von 1</p>
<h2>Warum Haus kaufen in Österreich attraktiv sein kann</h2>
<p>Dieser redaktionelle Text ist kein Inserat.</p>
<h3>Einfamilienhaus kaufen in 9220 Velden</h3>
<a href="https://portal.example/velden">SEEBLICK! Top saniertes Haus</a>
<div>€ 980.000,-</div>
<div>9220 Velden am Wörther See / 100m² / 4 Zimmer</div>
</body></html>
"""

PAGINATION_FIXTURE = """
<html><body>
<p>13 bis 24 von 4.396</p>
<h3>Haus kaufen in 3100 St. Pölten</h3>
<a href="https://portal.example/3">Haus auf Seite zwei</a>
<div>€ 410.000,-</div>
<div>3100 St. Pölten / 120m² / 5 Zimmer</div>
<nav>
  <a href="/immo/Haus-kaufen/Niederoesterreich">1</a>
  <a href="/immo/Haus-kaufen/Niederoesterreich/2">2</a>
  <a href="/immo/Haus-kaufen/Niederoesterreich/3">3</a>
  <a href="/immo/Haus-kaufen/Niederoesterreich/367">367</a>
  <a href="/immo/Haus-kaufen/Niederoesterreich/3">Weiter</a>
</nav>
</body></html>
"""


def test_stream_parser_keeps_location_and_area_with_nested_links() -> None:
    page = parse_immmo_search_page(
        FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Niederoesterreich",
    )

    assert page.reported_count == 24
    assert page.cards_seen == 2
    assert page.cards_parsed == 2
    assert len(page.items) == 2

    first = next(item for item in page.items if item.url.endswith("/object/1"))
    assert first.title == "Charmantes Haus mit Garten"
    assert first.price_eur == Decimal(249000)
    assert first.postal_code == "3950"
    assert first.city == "Gmünd"
    assert first.living_area_m2 == Decimal("132.66")
    assert first.plot_area_m2 == Decimal(368)
    assert first.raw_payload["source_heading_kind"] == "Haus"

    second = next(item for item in page.items if item.url.endswith("/2"))
    assert second.price_eur == Decimal(320000)
    assert second.postal_code == "2722"
    assert second.city == "Winzendorf"
    assert second.living_area_m2 == Decimal(100)
    assert second.plot_area_m2 == Decimal(410)
    assert second.raw_payload["source_heading_kind"] == "Doppelhaushälfte"


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
    assert page.cards_parsed == 2
    assert len(page.items) == 1


def test_result_headings_accept_subtypes_but_not_editorial_prose() -> None:
    page = parse_immmo_search_page(
        PROSE_HEADING_FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Kaernten",
    )

    assert page.reported_count == 1
    assert page.cards_seen == 1
    assert page.cards_parsed == 1
    assert len(page.items) == 1
    assert page.items[0].postal_code == "9220"
    assert page.items[0].city == "Velden am Wörther See"
    assert page.items[0].living_area_m2 == Decimal(100)
    assert page.items[0].raw_payload["source_heading_kind"] == "Einfamilienhaus"


def test_parser_reads_live_count_and_next_page_from_page_two() -> None:
    page = parse_immmo_search_page(
        PAGINATION_FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Niederoesterreich/2",
    )

    assert page.reported_count == 4396
    assert page.current_page == 2
    assert page.pagination_max_page == 367
    assert page.has_next_page is True
