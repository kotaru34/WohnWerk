from app.property_source_brand import property_source_brand


def test_known_house_sources_have_stable_branded_labels() -> None:
    expected = {
        "sreal.at": ("s REAL", "#e2001a", "s"),
        "immmo.at": ("IMMMO", "#e36f1e", "IM"),
        "immowelt-de": ("immowelt", "#f26a21", "iw"),
        "kleinanzeigen-de": ("Kleinanzeigen", "#00a878", "K"),
        "engel-voelkers-de": ("Engel & Völkers", "#8b1f2d", "E&V"),
        "immoscout24-de": ("ImmoScout24", "#ff7500", "24"),
        "von-poll-de": ("VON POLL", "#21384f", "VP"),
        "remax-de": ("RE/MAX", "#dc1c2e", "R/M"),
        "iad-de": ("iad", "#005a9c", "iad"),
        "falc-de": ("FALC", "#2b2b2b", "F"),
    }

    for source_name, values in expected.items():
        brand = property_source_brand(source_name)
        assert (brand.label, brand.color, brand.icon_text) == values


def test_unknown_source_has_readable_neutral_fallback() -> None:
    brand = property_source_brand("example-property-feed")

    assert brand.key == "source"
    assert brand.label == "example-property-feed"
    assert brand.color == "#6f7782"
    assert brand.icon_text == "EP"
