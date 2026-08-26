from decimal import Decimal

from app.sources.property.sreal_v2 import parse_sreal_search_page


def test_sreal_counts_unique_listing_ids_not_detail_anchors() -> None:
    html = """
    <html><body>
      <a href="/de/immobilie/2838-2215/landhaus"><img alt="Haus"></a>
      <a href="/de/immobilie/2838-2215/landhaus">
        Landhaus in idyllischer Lage
        <span>9814 Mühldorf</span>
        <span>300 m<sup>2</sup> Wohnfläche</span>
        <span>398.000 € Kaufpreis</span>
      </a>
      <a href="/de/immobilie/960-12345/pfarrhaus">
        Ehemaliges Pfarrhaus
        <span>3932 Kirchberg am Walde</span>
        <span>3.020 m² Grundfläche</span>
        <span>135.000 € Kaufpreis</span>
      </a>
      <a href="?p=2">2</a>
      <a href="?p=16">16</a>
    </body></html>
    """

    page = parse_sreal_search_page(
        html,
        page_url="https://www.sreal.at/de/haeuser-kauf/angebot/10?p=1",
    )

    assert page.raw_detail_anchors == 3
    assert page.duplicate_detail_anchors == 1
    assert page.cards_seen == 2
    assert page.cards_parsed == 2
    assert page.metadata_fallbacks == 0
    assert len(page.items) == 2

    first = next(item for item in page.items if item.source_listing_id == "2838-2215")
    assert first.postal_code == "9814"
    assert first.city == "Mühldorf"
    assert first.living_area_m2 == Decimal(300)
    assert first.price_eur == Decimal(398000)


def test_sreal_materializes_known_detail_id_when_search_metadata_is_sparse() -> None:
    html = """
    <html><body>
      <a href="/de/immobilie/111-22222/sparse-card">
        Besonderes Hausangebot
      </a>
    </body></html>
    """

    page = parse_sreal_search_page(
        html,
        page_url="https://www.sreal.at/de/haeuser-kauf/angebot/10?p=1",
    )

    assert page.cards_seen == 1
    assert page.cards_parsed == 1
    assert page.metadata_fallbacks == 1
    assert len(page.items) == 1
    item = page.items[0]
    assert item.source_listing_id == "111-22222"
    assert item.title == "Besonderes Hausangebot"
    assert item.postal_code is None
    assert item.raw_payload["search_metadata_complete"] is False
