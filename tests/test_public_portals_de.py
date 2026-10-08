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
        "de-public-frontier"
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
