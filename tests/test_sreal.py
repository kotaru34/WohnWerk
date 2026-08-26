from decimal import Decimal

from app.sources.property.sreal import parse_sreal_search_page

FIXTURE = """
<html><body>
<a href="/de/immobilie/2838-2215/landhaus-in-idyllischer-lage">
  Landhaus in idyllischer Lage Nähe Spittal/Drau
  <span>9814 Mühldorf</span>
  <span>300 m² Wohnfläche</span>
  <span>398.000 € Kaufpreis</span>
</a>
<a href="/de/immobilie/960-12345/ehemaliges-pfarrhaus">
  360° Ehemaliges Pfarrhaus mit großem Gartengrundstück
  <span>3932 Kirchberg am Walde</span>
  <span>3.020 m² Grundfläche</span>
  <span>135.000 € Kaufpreis</span>
</a>
<a href="/de/immobilie/960-77777/charmantes-landhaus">
  Charmantes Landhaus in 5273 Roßbach im Herzen des Innviertels
  <span>5273 Roßbach</span>
  <span>537 m² Grundfläche</span>
</a>
<a href="?p=2">2</a>
<a href="?p=17">17</a>
<a href="/de/wohnungen-kauf/angebot/11">Not a detail card</a>
</body></html>
"""


def test_sreal_search_parser_extracts_house_cards() -> None:
    page = parse_sreal_search_page(
        FIXTURE,
        page_url="https://www.sreal.at/de/haeuser-kauf/angebot/10?p=1",
    )

    assert page.max_page == 17
    assert page.cards_seen == 3
    assert page.cards_parsed == 3
    assert len(page.items) == 3

    first = next(item for item in page.items if item.source_listing_id == "2838-2215")
    assert first.title == "Landhaus in idyllischer Lage Nähe Spittal/Drau"
    assert first.postal_code == "9814"
    assert first.city == "Mühldorf"
    assert first.living_area_m2 == Decimal(300)
    assert first.plot_area_m2 is None
    assert first.price_eur == Decimal(398000)

    second = next(item for item in page.items if item.source_listing_id == "960-12345")
    assert second.postal_code == "3932"
    assert second.city == "Kirchberg am Walde"
    assert second.living_area_m2 is None
    assert second.plot_area_m2 == Decimal(3020)
    assert second.price_eur == Decimal(135000)

    third = next(item for item in page.items if item.source_listing_id == "960-77777")
    assert third.postal_code == "5273"
    assert third.city == "Roßbach"
    assert third.plot_area_m2 == Decimal(537)
    assert third.price_eur is None


def test_sreal_search_parser_uses_stable_detail_ids_and_urls() -> None:
    page = parse_sreal_search_page(
        FIXTURE,
        page_url="https://www.sreal.at/de/haeuser-kauf/angebot/10?p=1",
    )
    first = next(item for item in page.items if item.source_listing_id == "2838-2215")
    assert first.url == "https://www.sreal.at/de/immobilie/2838-2215/landhaus-in-idyllischer-lage"
