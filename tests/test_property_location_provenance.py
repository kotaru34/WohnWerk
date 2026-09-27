from datetime import UTC, datetime

from app.ingestion.properties import _enrich_property
from app.models import PostalCode, Property
from app.sources.base import RawProperty


def _item() -> RawProperty:
    return RawProperty(
        source_listing_id="de-1",
        url="https://example.test/de-1",
        title="Haus",
        postal_code="01067",
        city="Dresden",
    )


def test_sparse_postal_refresh_does_not_degrade_precise_property_location() -> None:
    precise_location = "SRID=4326;POINT(13.7373 51.0504)"
    property_row = Property(
        title="Haus",
        location=precise_location,
        location_source="provider",
        location_method="source_coordinate",
    )
    postal = PostalCode(
        postal_code="01067",
        name="Dresden",
        location="SRID=4326;POINT(13.72 51.05)",
        location_source="GeoNames DE postal code dump",
        location_method="postal_place_mean",
    )

    _enrich_property(property_row, item=_item(), postal=postal, now=datetime.now(UTC))

    assert property_row.location == precise_location
    assert property_row.location_source == "provider"
    assert property_row.location_method == "source_coordinate"


def test_postal_refresh_records_coarse_location_provenance_when_no_precise_point_exists() -> None:
    property_row = Property(title="Haus")
    postal = PostalCode(
        postal_code="01067",
        name="Dresden",
        location="SRID=4326;POINT(13.72 51.05)",
        location_source="GeoNames DE postal code dump",
        location_method="postal_place_mean",
    )

    _enrich_property(property_row, item=_item(), postal=postal, now=datetime.now(UTC))

    assert property_row.location == postal.location
    assert property_row.location_source == "GeoNames DE postal code dump"
    assert property_row.location_method == "postal_place_mean"
