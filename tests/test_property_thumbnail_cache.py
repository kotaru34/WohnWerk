from app.property_thumbnail_cache import (
    _balanced_srcset_url,
    _comparison_url,
    _LinkedThumbnailParser,
)


def test_balanced_srcset_candidate_is_selected() -> None:
    assert (
        _balanced_srcset_url(
            "https://img.example/large.jpg 1200w, "
            "https://img.example/thumb.jpg 240w, "
            "https://img.example/medium.jpg 640w"
        )
        == "https://img.example/medium.jpg"
    )


def test_balanced_srcset_does_not_jump_to_hero_when_medium_is_closer() -> None:
    assert (
        _balanced_srcset_url(
            "https://img.example/small.jpg 320w, "
            "https://img.example/medium.jpg 800w, "
            "https://img.example/hero.jpg 1600w"
        )
        == "https://img.example/medium.jpg"
    )


def test_balanced_density_prefers_sharper_candidate_on_tie() -> None:
    assert (
        _balanced_srcset_url(
            "https://img.example/normal.jpg 1x, https://img.example/retina.jpg 2x"
        )
        == "https://img.example/retina.jpg"
    )


def test_linked_thumbnail_is_bound_only_to_exact_listing_anchor() -> None:
    page_url = "https://www.immmo.at/immo/Haus-kaufen/Wien/3"
    parser = _LinkedThumbnailParser(page_url=page_url)
    parser.feed(
        """
        <a href="https://portal.example/expose/123?utm_source=immmo.at">
          <img
            src="https://img.example/medium.jpg"
            srcset="https://img.example/thumb.jpg 240w, https://img.example/large.jpg 1200w"
          >
          Haus mit Garten
        </a>
        <img src="https://img.example/unrelated.jpg">
        """
    )

    key = _comparison_url("https://portal.example/expose/123")
    assert parser.images == {key: "https://img.example/large.jpg"}


def test_comparison_url_drops_tracking_but_keeps_identity_query() -> None:
    assert _comparison_url(
        "https://portal.example/object?id=42&utm_medium=cooperation&utm_source=immmo.at"
    ) == "https://portal.example/object?id=42"


def test_thumbnail_parser_ignores_data_uri_placeholder() -> None:
    parser = _LinkedThumbnailParser(page_url="https://www.sreal.at/de/haeuser-kauf/angebot/10")
    parser.feed(
        """
        <a href="/de/immobilie/123/example">
          <img src="data:image/gif;base64,AAAA">
        </a>
        """
    )

    assert parser.images == {}
