from app.models import PropertyListing
from app.property_thumbnail_upgrade import THUMBNAIL_QUALITY_POLICY, _store_balanced_payload


def test_balanced_upgrade_updates_thumbnail_metadata_without_dropping_payload() -> None:
    listing = PropertyListing(
        property_id=1,
        source_id=1,
        source_listing_id="example",
        url="https://example.test/listing/1",
        raw_payload={"existing": "value", "thumbnail_url": "https://img.test/low.jpg"},
    )

    _store_balanced_payload(listing, "https://img.test/medium.jpg")

    assert listing.raw_payload["existing"] == "value"
    assert listing.raw_payload["thumbnail_url"] == "https://img.test/medium.jpg"
    assert listing.raw_payload["thumbnail_semantics"] == THUMBNAIL_QUALITY_POLICY
    assert listing.raw_payload["thumbnail_target_width_px"] == 720
