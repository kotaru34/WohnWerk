from app.property_thumbnail_cache import _comparison_url
from app.sources.base import RawProperty
from app.sources.property.thumbnail_capture import ImmmoThumbnailPropertySource


def test_crawl_capture_attaches_exact_listing_thumbnail() -> None:
    source = ImmmoThumbnailPropertySource(request_delay_seconds=0)
    source._reset_thumbnail_capture()
    listing_url = "https://portal.example/expose/123?utm_source=immmo.at"
    key = _comparison_url(listing_url)
    assert key is not None
    source._captured_thumbnails[key] = "https://images.example/thumb-123.jpg"

    item = RawProperty(
        source_listing_id="123",
        url=listing_url,
        title="Haus mit Garten",
        raw_payload={"format": "fixture"},
    )

    assert source._attach_captured_thumbnails([item]) == 1
    assert item.raw_payload["thumbnail_url"] == "https://images.example/thumb-123.jpg"
    assert item.raw_payload["thumbnail_semantics"] == "search_card_exact_anchor"


def test_crawl_capture_does_not_guess_thumbnail_for_unmatched_listing() -> None:
    source = ImmmoThumbnailPropertySource(request_delay_seconds=0)
    source._reset_thumbnail_capture()
    source._captured_thumbnails[
        "https://portal.example/expose/other"
    ] = "https://images.example/other.jpg"

    item = RawProperty(
        source_listing_id="123",
        url="https://portal.example/expose/123",
        title="Haus mit Garten",
    )

    assert source._attach_captured_thumbnails([item]) == 0
    assert "thumbnail_url" not in item.raw_payload
