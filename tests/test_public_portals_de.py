"""Offline contract tests; live provider validation is a separate deployment gate."""
from decimal import Decimal

import pytest

from app.sources.property.public_portals_de import (
    IMMOBILIEN_DE,
    OHNE_MAKLER,
    ImmobilienDeGermanyPropertySource,
    OhneMaklerGermanyPropertySource,
    _canonical_listing,
    parse_public_portal_page,
)


def test_ohne_makler_full_clickable_card_extracts_public_facts() -> None:
    html = """
        <main><article><a href="/immobilie/503161/">
        120.000 € Ein älteres Einfamilienhaus im Grünen 17213 Fünfseen
        5 145m² 800m²
        </a></article></main>
    """
    items, seen = parse_public_portal_page(
        html, page_url=OHNE_MAKLER.base_url + OHNE_MAKLER.search_path, portal=OHNE_MAKLER
    )
    assert seen == 1
    assert len(items) == 1
    item = items[0]
    assert item.source_listing_id == "503161"
    assert item.title == "Ein älteres Einfamilienhaus im Grünen"
    assert item.price_eur == Decimal(120000)
    assert item.postal_code == "17213"
    assert item.city == "Fünfseen"
    assert item.living_area_m2 == Decimal(145)
    assert item.plot_area_m2 == Decimal(800)
    assert item.raw_payload["frontier_only"] is True


def test_immobilien_de_link_and_separate_card_metadata() -> None:
    html = """
        <main><article>
        <a href="/expose/10011804">Das bezahlbare Einfamilienhaus am Wald</a>
        <p>189.000 € Kaufpreis</p>
        <p>01917 Kamenz</p><p>Fläche 130 m²</p><p>Zimmer 5</p>
        </article></main>
    """
    items, seen = parse_public_portal_page(
        html, page_url=IMMOBILIEN_DE.base_url + IMMOBILIEN_DE.search_path,
        portal=IMMOBILIEN_DE,
    )
    assert seen == 1
    assert len(items) == 1
    assert items[0].title == "Das bezahlbare Einfamilienhaus am Wald"
    assert items[0].city == "Kamenz"
    assert items[0].price_eur == Decimal(189000)
    assert items[0].living_area_m2 == Decimal(130)


def test_price_policy_discards_expensive_or_rental_cards() -> None:
    html = """
        <article><a href="/immobilie/1/">799.000 € Haus am See 17213 Fünfseen 130m²</a></article>
        <article><a href="/immobilie/2/">1.200 € Mietobjekt 17213 Fünfseen 130m²</a></article>
    """
    items, seen = parse_public_portal_page(
        html, page_url=OHNE_MAKLER.base_url + OHNE_MAKLER.search_path, portal=OHNE_MAKLER
    )
    assert seen == 2
    assert items == []


@pytest.mark.parametrize(
    "href",
    [
        "https://evil.example/immobilie/503161/",
        "http://www.ohne-makler.net/immobilie/503161/",
        "/immobilie/503161/file/1",
        "/immobilie/not-numeric/",
        "//www.ohne-makler.net.evil.example/immobilie/503161/",
    ],
)
def test_portal_url_validation_rejects_wrong_hosts_and_paths(href: str) -> None:
    assert _canonical_listing(
        href, page_url=OHNE_MAKLER.base_url + OHNE_MAKLER.search_path,
        portal=OHNE_MAKLER,
    ) is None


def test_both_sources_use_bounded_non_authoritative_shards() -> None:
    ohne_makler = OhneMaklerGermanyPropertySource()
    immobilien_de = ImmobilienDeGermanyPropertySource()
    assert OHNE_MAKLER.search_path == "/immobilien/haus-kaufen/"
    assert [shard.key for shard in ohne_makler.default_shards()] == [
        "de-public-frontier",
        "de-bayern",
        "de-baden-wurttemberg",
        "de-rheinland-pfalz",
        "de-nordrhein-westfalen",
        "de-sachsen",
        "de-sachsen-anhalt",
        "de-brandenburg",
        "de-mecklenburg-vorpommern",
        "de-thuringen",
    ]
    assert [shard.key for shard in immobilien_de.default_shards()] == [
        "de-public-frontier",
        "de-neubrandenburg",
        "de-gangelt",
        "de-homburg",
        "de-hagenow",
    ]
    for adapter in (ohne_makler, immobilien_de):
        shards = adapter.default_shards()
        assert len(shards) == len(adapter.frontier_paths())
        assert len({shard.key for shard in shards}) == len(shards)
        assert all(shard.params == {"country_code": "DE"} for shard in shards)
        assert all(shard.result_cap == 50 for shard in shards)
        assert all(
            path.startswith("/") and "?" not in path
            for path in adapter.frontier_paths().values()
        )


def test_immobilien_de_prefers_title_link_to_separate_image_link() -> None:
    html = """
        <div><a href="/expose/9794876"><img alt="Foto der Doppelhaushälfte"></a>
            <a href="/expose/9794876">Neubrandenburg: Doppelhaushälfte mit Keller</a>
            <p>139.000 € Kaufpreis</p><p>1.448 € / m²</p>
            <p>17034 Neubrandenburg</p><p>Fläche 96 m²</p>
        </div>
    """
    items, seen = parse_public_portal_page(
        html, page_url=IMMOBILIEN_DE.base_url + "/kaufen/haus/neubrandenburg/",
        portal=IMMOBILIEN_DE,
    )
    assert seen == 1
    assert len(items) == 1
    assert items[0].title == "Neubrandenburg: Doppelhaushälfte mit Keller"
    assert items[0].price_eur == Decimal(139000)
    assert items[0].url == "https://www.immobilien.de/expose/9794876"


def test_image_only_card_does_not_invent_title_from_kaufpreis_metrics() -> None:
    html = """
        <div><a href="/expose/9794876"><img alt="house"></a>
            <p>139.000 € Kaufpreis 1.448 € / m²</p>
            <p>17034 Neubrandenburg</p><p>Fläche 96 m²</p>
        </div>
    """
    items, seen = parse_public_portal_page(
        html, page_url=IMMOBILIEN_DE.base_url + IMMOBILIEN_DE.search_path,
        portal=IMMOBILIEN_DE,
    )
    assert seen == 1
    assert items == []


def test_same_id_different_card_anchors_are_not_counted_as_multiple_listings() -> None:
    html = """
        <article>
            <a href="/immobilie/503042/"><img alt="Ferienhaus"></a>
            <a href="/immobilie/503042/">135.000 € Ferienhaus mit Bootsanleger
                17111 Sommersdorf 3 85m² 540m²</a>
        </article>
    """
    items, seen = parse_public_portal_page(
        html, page_url=OHNE_MAKLER.base_url + OHNE_MAKLER.search_path,
        portal=OHNE_MAKLER,
    )
    assert seen == 1
    assert len(items) == 1
    assert items[0].title == "Ferienhaus mit Bootsanleger"


def test_canonical_immobilien_de_original_expose_link_omits_trailing_slash() -> None:
    assert _canonical_listing(
        "/expose/9658417/", page_url=IMMOBILIEN_DE.base_url + IMMOBILIEN_DE.search_path,
        portal=IMMOBILIEN_DE,
    ) == ("https://www.immobilien.de/expose/9658417", "9658417")


def test_immobilien_de_ignores_small_per_square_metre_price_when_markup_is_reordered() -> None:
    html = """
        <article>
            <a href="/expose/9658417">Wohnhaus und Werkstatt in Ebersdorf b. Coburg</a>
            <p>1.039 € / m²</p><p>185.000 €Kaufpreis</p>
            <p>96237 Ebersdorf bei Coburg</p><p>Fläche 178 m²</p>
        </article>
    """
    items, seen = parse_public_portal_page(
        html, page_url=IMMOBILIEN_DE.base_url + IMMOBILIEN_DE.search_path,
        portal=IMMOBILIEN_DE,
    )
    assert seen == 1
    assert len(items) == 1
    assert items[0].price_eur == Decimal(185000)


def test_immobilien_de_does_not_infer_asking_price_from_unlabeled_metrics() -> None:
    html = """
        <article>
            <a href="/expose/9658417">Das kleine Wohnhaus in Coburg</a>
            <p>1.039 € / m²</p><p>Preis auf Anfrage</p>
            <p>96237 Ebersdorf bei Coburg</p><p>Fläche 178 m²</p>
        </article>
    """
    items, seen = parse_public_portal_page(
        html, page_url=IMMOBILIEN_DE.base_url + IMMOBILIEN_DE.search_path,
        portal=IMMOBILIEN_DE,
    )
    assert seen == 1
    assert items == []


@pytest.mark.parametrize("title", [
    "VERKAUFT!! Renoviertes Einfamilienhaus",
    "RESERVIERT! Günstiges Haus mit Garten",
    "Hauspreis ohne Grundstück: Bungalow am See",
    "Kleines Haus auf Pachtgrundstück verfügbar",
])
def test_sale_frontier_skips_sold_or_build_only_offers(title: str) -> None:
    html = (
        f'<article><a href="/immobilie/97531/">'
        f'159.000 € {title} 17034 Neubrandenburg 110m² 500m²'
        '</a></article>'
    )
    items, seen = parse_public_portal_page(
        html, page_url=OHNE_MAKLER.base_url + OHNE_MAKLER.search_path,
        portal=OHNE_MAKLER,
    )
    assert seen == 1
    assert items == []


def test_german_market_paths_include_non_eastern_low_budget_opportunities() -> None:
    adapter = OhneMaklerGermanyPropertySource()
    assert adapter.frontier_paths()["de-bayern"] == "/immobilien/haus-kaufen/bayern/"
    assert adapter.frontier_paths()["de-baden-wurttemberg"].endswith("/baden-wurttemberg/")
    assert adapter.frontier_paths()["de-rheinland-pfalz"].endswith("/rheinland-pfalz/")
    assert adapter.frontier_paths()["de-nordrhein-westfalen"].endswith("/nordrhein-westfalen/")
