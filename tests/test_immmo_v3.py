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
<h3>Haus kaufen in 2700 Wiener Neustadt</h3>
<a href="https://other.example/normal-object">Kleines Stadthaus</a>
<div>€ 279.000,-</div>
<div>2700 Wiener Neustadt / 92m² / 4 Zimmer</div>
<h3>Haus kaufen in 7000 Eisenstadt</h3>
<div>Linkloses Haus mit Innenhof</div>
<div>€ 319.000,-</div>
<div>7000 Eisenstadt / 110m² / 4 Zimmer</div>
<nav>
  <a href="/immo/Haus-kaufen/Niederoesterreich/2">2</a>
  <a href="/immo/Haus-kaufen/Niederoesterreich/10">10</a>
  <span>...</span><span>367</span>
</nav>
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
    assert wrapped.raw_payload["original_url_missing"] is False

    synthetic = next(item for item in page.items if item.postal_code == "7000")
    assert "/wohnwerk-fallback/" in synthetic.url
    assert synthetic.title == "Linkloses Haus mit Innenhof"
    assert synthetic.living_area_m2 == Decimal(110)
    assert synthetic.raw_payload["original_url_missing"] is True


def test_linkless_card_identity_is_stable_across_scans() -> None:
    first = next(item for item in _parse_fixture().items if item.postal_code == "7000")
    second = next(item for item in _parse_fixture().items if item.postal_code == "7000")

    assert first.source_listing_id == second.source_listing_id
    assert first.url == second.url


def test_full_target_comes_from_reported_count_not_visible_pagination_window() -> None:
    page = _parse_fixture()

    assert page.pagination_max_page == 10
    assert page.reported_count == 4396
    assert (page.reported_count + 11) // 12 == 367
