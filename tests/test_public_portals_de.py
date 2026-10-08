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
    for adapter in (OhneMaklerGermanyPropertySource(), ImmobilienDeGermanyPropertySource()):
        shards = adapter.default_shards()
        assert len(shards) == 1
        assert shards[0].key == "de-public-frontier"
        assert shards[0].params["country_code"] == "DE"
