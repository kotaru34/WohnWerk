from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal

from app.ingestion.properties import _enrich_property
from app.internet_access import (
    BBA_SPEED_CLASSES,
    BBA_TECHNOLOGIES,
    BroadbandGridCell,
    InternetEvidenceView,
    LOCATION_PRECISION_POSTAL_CENTROID,
    LOCATION_PRECISION_SOURCE_EXACT,
    assess_internet_evidence,
    lookup_breitbandatlas_grid,
    parse_immoscout_telekom_internet,
    property_grid_eligible,
    validate_breitbandatlas_gpkg,
)
from app.models import PostalCode, Property
from app.sources.base import RawProperty


def _telekom_html(*, scout_id: str = "123456789", available: str = "true", speed: int = 250) -> str:
    return (
        f'<script>"obj_scoutId":"{scout_id}",'
        f'"obj_telekomInternetAvailable":"{available}",'
        f'"obj_telekomInternetSpeed":"{speed} MBit/s",'
        '"obj_telekomInternetUrlBase":"https://www.telekom.de/netz/"</script>'
    )


def _internet_view(speed: int | None, *, state: str = "available") -> InternetEvidenceView:
    return InternetEvidenceView(
        source_name="test",
        source_reference="ref",
        evidence_kind="test",
        evidence_precision="listing_specific_provider",
        provider_name="Provider",
        availability_state=state,
        max_download_mbps=speed,
        technology=None,
        coverage_percent=None,
        monthly_price_eur=None,
        source_url="https://example.test/",
        dataset_date=None,
        source_payload={},
    )


def _synthetic_gpkg(path) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "create table gpkg_contents ("
        "table_name text, data_type text, identifier text, description text, "
        "last_change text, min_x real, min_y real, max_x real, max_y real, srs_id integer)"
    )
    connection.execute(
        "create table gpkg_geometry_columns ("
        "table_name text, column_name text, geometry_type_name text, "
        "srs_id integer, z integer, m integer)"
    )
    column_sql = [
        "id integer primary key",
        "geom blob",
        "raster_id text",
        "ags text",
    ]
    column_sql.extend(
        f'"down_fn_hh_{technology}_{speed}" real'
        for technology in BBA_TECHNOLOGIES
        for speed in BBA_SPEED_CLASSES
    )
    connection.execute(f'create table grid ({",".join(column_sql)})')
    connection.execute(
        "create table rtree_grid_geom ("
        "id integer primary key, minx real, maxx real, miny real, maxy real)"
    )
    connection.execute(
        "insert into gpkg_contents "
        "(table_name,data_type,identifier,srs_id) values ('grid','features','grid',25832)"
    )
    connection.execute(
        "insert into gpkg_geometry_columns "
        "values ('grid','geom','POLYGON',25832,0,0)"
    )

    columns = ["id", "geom", "raster_id", "ags"] + [
        f"down_fn_hh_{technology}_{speed}"
        for technology in BBA_TECHNOLOGIES
        for speed in BBA_SPEED_CLASSES
    ]
    values: list[object] = [1, b"", "100m-test", "11000000"]
    for technology in BBA_TECHNOLOGIES:
        for speed in BBA_SPEED_CLASSES:
            if technology == "alle" and speed <= 400:
                values.append(100.0)
            elif technology == "alle" and speed == 1000:
                values.append(76.5)
            else:
                values.append(0.0)
    placeholders = ",".join("?" for _ in columns)
    connection.execute(
        f'insert into grid ({",".join(columns)}) values ({placeholders})',
        values,
    )
    connection.execute(
        "insert into rtree_grid_geom values (1,0,10000000,0,10000000)"
    )
    connection.commit()
    connection.close()


def test_immoscout_telekom_parser_preserves_listing_specific_speed() -> None:
    evidence = parse_immoscout_telekom_internet(
        _telekom_html(),
        expected_scout_id="123456789",
    )

    assert evidence is not None
    assert evidence.scout_id == "123456789"
    assert evidence.availability_state == "available"
    assert evidence.max_download_mbps == 250
    assert evidence.provider_url == "https://www.telekom.de/netz/"


def test_immoscout_telekom_unavailable_does_not_retain_speed() -> None:
    evidence = parse_immoscout_telekom_internet(
        _telekom_html(available="false", speed=1000),
        expected_scout_id="123456789",
    )

    assert evidence is not None
    assert evidence.availability_state == "unavailable"
    assert evidence.max_download_mbps is None


def test_immoscout_telekom_parser_rejects_identity_mismatch() -> None:
    assert (
        parse_immoscout_telekom_internet(
            _telekom_html(scout_id="111"),
            expected_scout_id="222",
        )
        is None
    )


def test_immoscout_telekom_parser_requires_explicit_internet_fields() -> None:
    assert (
        parse_immoscout_telekom_internet(
            '<script>"obj_scoutId":"123456789"</script>',
            expected_scout_id="123456789",
        )
        is None
    )


def test_grid_speed_requires_effectively_full_cell_coverage() -> None:
    cell = BroadbandGridCell(
        raster_id="100m-test",
        ags="11000000",
        coverage_all={
            10: Decimal(100),
            16: Decimal(100),
            30: Decimal(100),
            50: Decimal(100),
            100: Decimal(100),
            200: Decimal(100),
            400: Decimal(100),
            1000: Decimal("99.5"),
        },
        coverage_by_technology={},
    )

    assert cell.max_defensible_download_mbps == 400


def test_breitbandatlas_validation_and_lookup_use_grid_not_address_claim(tmp_path) -> None:
    path = tmp_path / "grid.gpkg"
    _synthetic_gpkg(path)

    info = validate_breitbandatlas_gpkg(path)
    cell = lookup_breitbandatlas_grid(path, longitude=13.405, latitude=52.52)

    assert info.table_name == "grid"
    assert info.feature_count == 1
    assert len(info.artifact_sha256) == 64
    assert cell is not None
    assert cell.raster_id == "100m-test"
    assert cell.coverage_all[1000] == Decimal("76.500")
    assert cell.max_defensible_download_mbps == 400


def test_postal_centroid_is_never_eligible_for_100m_grid_lookup() -> None:
    property_row = Property(location=object(), location_precision=LOCATION_PRECISION_POSTAL_CENTROID)
    exact_row = Property(location=object(), location_precision=LOCATION_PRECISION_SOURCE_EXACT)

    assert property_grid_eligible(property_row) is False
    assert property_grid_eligible(exact_row) is True


def test_postal_refresh_does_not_overwrite_existing_exact_location() -> None:
    exact_location = object()
    postal_location = object()
    property_row = Property(
        title="Haus",
        location=exact_location,
        location_precision=LOCATION_PRECISION_SOURCE_EXACT,
    )
    postal = PostalCode(
        postal_code="10115",
        name="Berlin",
        location=postal_location,
    )

    _enrich_property(
        property_row,
        item=RawProperty(
            source_listing_id="1",
            url="https://example.test/1",
            title="Haus",
            postal_code="10115",
        ),
        postal=postal,
        now=datetime(2026, 9, 27, tzinfo=UTC),
    )

    assert property_row.location is exact_location
    assert property_row.location_precision == LOCATION_PRECISION_SOURCE_EXACT
    assert property_row.postal_code == "10115"


def test_assessment_meets_minimum_without_starlink_fallback() -> None:
    assessment = assess_internet_evidence(
        1,
        (_internet_view(250),),
        minimum_download_mbps=100,
    )

    assert assessment.status == "sufficient"
    assert assessment.max_defensible_download_mbps == 250
    assert assessment.starlink_fallback is False


def test_assessment_below_minimum_exposes_starlink_only_as_fallback() -> None:
    assessment = assess_internet_evidence(
        1,
        (_internet_view(50),),
        minimum_download_mbps=100,
    )

    assert assessment.status == "insufficient"
    assert assessment.starlink_fallback is True


def test_assessment_unknown_exposes_starlink_fallback_without_inventing_speed() -> None:
    assessment = assess_internet_evidence(
        1,
        (),
        minimum_download_mbps=100,
    )

    assert assessment.status == "unknown"
    assert assessment.max_defensible_download_mbps is None
    assert assessment.starlink_fallback is True
