from decimal import Decimal

from app.sources.property.immmo_v3 import parse_immmo_search_page

WRAPPED_CARD_FIXTURE = """
<html><body>
<p>1 bis 12 von 4396</p>
<a href="https://portal.example/wrapped-object">
  <h3>Einfamilienhaus kaufen in 3100 St. Pölten</h3>
  <span>Haus mit Garten in ruhiger Lage</span>
  <span>€ 449.000,-</span>
  <span>3100 St. Pölten / 145m² / 5 Zimmer</span>
</a>
<div>Wohnfläche: 145 m²</div>
<h3>Haus kaufen in 2700 Wiener Neustadt</h3>
<a href="https://other.example/normal-object">Kleines Stadthaus</a>
<div>€ 279.000,-</div>
<div>2700 Wiener Neustadt / 92m² / 4 Zimmer</div>
<div>Mit einer Wohnfläche von 92 m² ideal für eine kleine Familie.</div>
<h3>Haus kaufen in 7000 Eisenstadt</h3>
<div>Linkloses Haus mit Innenhof</div>
<div>€ 319.000,-</div>
<div>7000 Eisenstadt / 110m² / 4 Zimmer</div>
<div>Rund 110 m² Wohnfläche mit Innenhof.</div>
<nav>
  <a href="/immo/Haus-kaufen/Niederoesterreich/2">2</a>
  <a href="/immo/Haus-kaufen/Niederoesterreich/10">10</a>
  <span>...</span><span>367</span>
</nav>
</body></html>
"""

AREA_SEMANTICS_FIXTURE = """
<html><body>
<p>1 bis 12 von 2</p>
<h3>Haus kaufen in 8052 Graz</h3>
<a href="https://www.findmyhome.at/5728144">Kleines Gartenparadies mit Gartenhaus, Terrasse &amp; Teich</a>
<div>€ 41.000,-</div>
<div>8052 Graz / 7.246,04m²</div>
<div>Grundstücksfläche ca. 7.246,04 m². Gartenhaus mit 20 m² Nutzfläche.</div>
<h3>Bauernhaus kaufen in 6391 Fieberbrunn</h3>
<a href="https://www.findmyhome.at/5655601">Historisches Bauernhaus mit Freizeitwohnsitz</a>
<div>€ 790.000,-</div>
<div>6391 Fieberbrunn / 748m² / 5 Zimmer</div>
<div>Insgesamt bietet die Liegenschaft auf knapp 130 m² Wohn-Nutzfläche vielseitige Möglichkeiten. Grundstücksfläche ca. 748 m².</div>
</body></html>
"""


def _parse_fixture():
    return parse_immmo_search_page(
        WRAPPED_CARD_FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Niederoesterreich",
    )


def test_parser_accepts_wrapped_links_and_preserves_linkless_cards() -> None:
    page = _parse_fixture()

    assert page.reported_count == 4396
    assert page.cards_seen == 3
    assert page.cards_parsed == 3
    assert len(page.items) == 3

    wrapped = next(item for item in page.items if item.url.endswith("/wrapped-object"))
    assert wrapped.postal_code == "3100"
    assert wrapped.city == "St. Pölten"
    assert wrapped.living_area_m2 == Decimal(145)
    assert wrapped.price_eur == Decimal(449000)
    assert wrapped.raw_payload["display_area_m2"] == "145"
    assert wrapped.raw_payload["display_area_semantics"] == "living_explicit_primary"
    assert wrapped.raw_payload["original_url_missing"] is False
    assert wrapped.raw_payload["identity_stable"] is True

    synthetic = next(item for item in page.items if item.postal_code == "7000")
    assert "/wohnwerk-fallback/" in synthetic.url
    assert synthetic.title == "Linkloses Haus mit Innenhof"
    assert synthetic.living_area_m2 == Decimal(110)
    assert synthetic.raw_payload["display_area_m2"] == "110"
    assert synthetic.raw_payload["original_url_missing"] is True
    assert synthetic.raw_payload["identity_stable"] is False


def test_linkless_card_identity_is_repeatable_but_not_authoritative() -> None:
    first = next(item for item in _parse_fixture().items if item.postal_code == "7000")
    second = next(item for item in _parse_fixture().items if item.postal_code == "7000")

    assert first.source_listing_id == second.source_listing_id
    assert first.url == second.url
    assert first.raw_payload["identity_stable"] is False


def test_full_target_comes_from_reported_count_not_visible_pagination_window() -> None:
    page = _parse_fixture()

    assert page.pagination_max_page == 10
    assert page.reported_count == 4396
    assert (page.reported_count + 11) // 12 == 367


def test_plot_primary_display_area_is_not_promoted_to_living_area() -> None:
    page = parse_immmo_search_page(
        AREA_SEMANTICS_FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Steiermark",
    )
    garden = next(item for item in page.items if item.postal_code == "8052")

    assert garden.living_area_m2 is None
    assert garden.plot_area_m2 == Decimal("7246.04")
    assert garden.raw_payload["display_area_m2"] == "7246.04"
    assert garden.raw_payload["display_area_semantics"] == "plot_explicit_primary"
    assert garden.raw_payload["explicit_living_area_m2"] is None
    assert garden.raw_payload["explicit_plot_area_m2"] == "7246.04"


def test_explicit_living_area_wins_when_primary_display_is_plot_area() -> None:
    page = parse_immmo_search_page(
        AREA_SEMANTICS_FIXTURE,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Tirol",
    )
    farmhouse = next(item for item in page.items if item.postal_code == "6391")

    assert farmhouse.living_area_m2 == Decimal(130)
    assert farmhouse.plot_area_m2 == Decimal(748)
    assert farmhouse.raw_payload["display_area_m2"] == "748"
    assert farmhouse.raw_payload["display_area_semantics"] == "living_explicit_display_plot"
    assert farmhouse.raw_payload["explicit_living_area_m2"] == "130"
    assert farmhouse.raw_payload["explicit_plot_area_m2"] == "748"
