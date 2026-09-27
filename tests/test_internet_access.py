from __future__ import annotations

import sqlite3
import struct

from pyproj import Transformer
from shapely import Polygon, to_wkb

from app.internet_access import (
    BBA_SPEED_CLASSES,
    BBA_TECHNOLOGIES,
    PropertyInternetEvidence,
    lookup_breitbandatlas_grid,
    starlink_fallback_recommended,
    validate_breitbandatlas_gpkg,
)
from app.property_location import internet_location_is_precise


def _gpkg_geometry(polygon: Polygon) -> bytes:
    # GeoPackage binary header: GP, version 0, little-endian/no-envelope flags,
    # EPSG:25832, then ordinary WKB.
    return b"GP\x00\x01" + struct.pack("<i", 25832) + to_wkb(polygon)


def _synthetic_gpkg(path) -> None:
    table = "Versorgungsdaten_Gitterzellen_Stand_20251231"
    with sqlite3.connect(path) as connection:
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
        household_columns = [
            f'down_fn_hh_{technology}_{speed} real'
            for technology in BBA_TECHNOLOGIES
            for speed in BBA_SPEED_CLASSES
        ]
        connection.execute(
            f'create table "{table}" ('
            "id integer primary key, geom blob, raster_id text, raster_rowid integer, ags text, "
            + ",".join(household_columns)
            + ")"
        )
        rtree = f"rtree_{table}_geom"
        connection.execute(
            f'create virtual table "{rtree}" using rtree(id,minx,maxx,miny,maxy)'
        )
        connection.execute(
            "insert into gpkg_contents "
            "(table_name,data_type,identifier,min_x,min_y,max_x,max_y,srs_id) "
            "values (?,?,?,?,?,?,?,?)",
            (table, "features", table, 398200.0, 5268200.0, 398300.0, 5268300.0, 25832),
        )
        connection.execute(
            "insert into gpkg_geometry_columns values (?,?,?,?,?,?)",
            (table, "geom", "POLYGON", 25832, 0, 0),
        )

        polygon = Polygon(
            [
                (398200.0, 5268200.0),
                (398300.0, 5268200.0),
                (398300.0, 5268300.0),
                (398200.0, 5268300.0),
                (398200.0, 5268200.0),
            ]
        )
        values: dict[str, float | None] = {
            f"down_fn_hh_{technology}_{speed}": None
            for technology in BBA_TECHNOLOGIES
            for speed in BBA_SPEED_CLASSES
        }
        values.update(
            {
                "down_fn_hh_alle_30": 100.0,
                "down_fn_hh_alle_100": 100.0,
                "down_fn_hh_alle_1000": 77.14,
                "down_fn_hh_ftth_1000": 77.14,
            }
        )
        columns = ["id", "geom", "raster_id", "raster_rowid", "ags", *values]
        placeholders = ",".join("?" for _ in columns)
        connection.execute(
            f'insert into "{table}" ({",".join(columns)}) values ({placeholders})',
            [
                1,
                _gpkg_geometry(polygon),
                "100mN52682E3982",
                38170174,
                "08336105",
                *values.values(),
            ],
        )
        connection.execute(
            f'insert into "{rtree}" values (?,?,?,?,?)',
            (1, 398199.9375, 398300.0625, 5268199.5, 5268300.5),
        )


def test_breitbandatlas_validator_and_rtree_lookup_preserve_grid_semantics(tmp_path) -> None:
    path = tmp_path / "bba.gpkg"
    _synthetic_gpkg(path)

    descriptor = validate_breitbandatlas_gpkg(path)
    assert descriptor.table_name == "Versorgungsdaten_Gitterzellen_Stand_20251231"

    to_wgs84 = Transformer.from_crs(25832, 4326, always_xy=True)
    longitude, latitude = to_wgs84.transform(398250.0, 5268250.0)
    evidence = lookup_breitbandatlas_grid(
        path,
        longitude=longitude,
        latitude=latitude,
    )

    assert evidence is not None
    assert evidence.raster_id == "100mN52682E3982"
    assert evidence.municipality_ags == "08336105"
    assert evidence.coverage_by_speed["30"] == 100.0
    assert evidence.coverage_by_speed["100"] == 100.0
    assert evidence.coverage_by_speed["1000"] == 77.14
    assert evidence.coverage_by_technology["ftth"]["1000"] == 77.14
    assert evidence.max_grid_mbps == 1000
    assert evidence.max_full_coverage_mbps == 100


def test_postal_centroids_are_explicitly_ineligible_for_100m_broadband_lookup() -> None:
    assert internet_location_is_precise("postal_place_mean") is False
    assert internet_location_is_precise("address_mean") is False
    assert internet_location_is_precise(None) is False
    assert internet_location_is_precise("source_coordinate") is True
    assert internet_location_is_precise("address_geocode") is True


def test_starlink_fallback_is_triggered_by_missing_or_insufficient_fixed_evidence() -> None:
    assert starlink_fallback_recommended(None, minimum_fixed_mbps=100) is True

    evidence = PropertyInternetEvidence(
        property_id=1,
        source_name="breitbandatlas-de-grid",
        max_full_coverage_mbps=50,
    )
    assert starlink_fallback_recommended(evidence, minimum_fixed_mbps=100) is True

    evidence.max_full_coverage_mbps = 200
    assert starlink_fallback_recommended(evidence, minimum_fixed_mbps=100) is False
    assert starlink_fallback_recommended(evidence, minimum_fixed_mbps=None) is False
