from app.sources.property.immmo_v3 import parse_immmo_search_page


def test_unrelated_external_anchor_is_not_bound_to_card() -> None:
    html = """
    <html><body>
      <p>1 bis 12 von 1</p>
      <h3>Haus kaufen in 1160 Wien</h3>
      <div>KAPITALANLAGE DER BESONDEREN ART - Mitten in Wien</div>
      <a href="https://www.immobilienscout24.at/expose/6579d6eabfd5ce3bcce77d0a">Mehr</a>
      <div>€ 229.000,-</div>
      <div>1160 Wien / 96m²</div>
    </body></html>
    """

    page = parse_immmo_search_page(
        html,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Wien",
    )

    assert len(page.items) == 1
    item = page.items[0]
    assert item.title.startswith("KAPITALANLAGE DER BESONDEREN ART")
    assert "/wohnwerk-fallback/" in item.url
    assert item.raw_payload["original_url_missing"] is True
    assert item.raw_payload["identity_stable"] is False


def test_matching_title_anchor_remains_authoritative() -> None:
    html = """
    <html><body>
      <p>1 bis 12 von 1</p>
      <h3>Haus kaufen in 8010 Graz</h3>
      <a href="https://portal.example/house">Haus mit Garten in ruhiger Lage</a>
      <div>€ 149.000,-</div>
      <div>8010 Graz / 120m²</div>
    </body></html>
    """

    page = parse_immmo_search_page(
        html,
        page_url="https://www.immmo.at/immo/Haus-kaufen/Steiermark",
    )

    item = page.items[0]
    assert item.url == "https://portal.example/house"
    assert item.raw_payload["original_url_missing"] is False
    assert item.raw_payload["identity_stable"] is True
