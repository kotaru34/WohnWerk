from __future__ import annotations

import sqlite3

from pyproj import Transformer

from app.internet_access import (
    BBA_GPKG_TABLE,
    BBA_SPEEDS_MBIT,
    BBA_TECHNOLOGIES,
    BroadbandGridLookup,
    property_location_precise_enough,
    starlink_fallback_reason,
)


def _grid_fixture(tmp_path):
    path = tmp_path / "bba.gpkg"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE gpkg_contents (
            table_name TEXT PRIMARY KEY,
            data_type TEXT,
            identifier TEXT,
            description TEXT,
            last_change TEXT,
            min_x DOUBLE,
            min_y DOUBLE,
            max_x DOUBLE,
            max_y DOUBLE,
            srs_id INTEGER
        )
        """
    )
    connection.execute(
        "INSERT INTO gpkg_contents(table_name,data_type,identifier,srs_id) VALUES(?,?,?,?)",
        (BBA_GPKG_TABLE, "features", BBA_GPKG_TABLE, 25832),
    )

    columns = [
        "id INTEGER PRIMARY KEY",
        "geom BLOB",
        "raster_id TEXT",
        "ags TEXT",
    ]
    columns.extend(f"down_fn_hh_alle_{speed} FLOAT" for speed in BBA_SPEEDS_MBIT)
    for tech in BBA_TECHNOLOGIES:
        columns.extend(f"down_fn_hh_{tech}_{speed} FLOAT" for speed in BBA_SPEEDS_MBIT)
    connection.execute(f'CREATE TABLE "{BBA_GPKG_TABLE}" ({", ".join(columns)})')

    rtree = f"rtree_{BBA_GPKG_TABLE}_geom"
    connection.execute(
        f'CREATE TABLE "{rtree}" (id INTEGER, minx FLOAT, maxx FLOAT, miny FLOAT, maxy FLOAT)'
    )

    longitude, latitude = 13.404954, 52.520008
    x, y = Transformer.from_crs(4326, 25832, always_xy=True).transform(longitude, latitude)

    names = ["id", "geom", "raster_id", "ags"]
    values = [1, b"", "100mNTESTE0001", "11000000"]
    coverage = {
        10: 100.0,
        16: 100.0,
        30: 100.0,
        50: 100.0,
        100: 100.0,
        200: 82.5,
        400: 25.0,
        1000: 0.0,
    }
    for speed in BBA_SPEEDS_MBIT:
        names.append(f"down_fn_hh_alle_{speed}")
        values.append(coverage[speed])
    for tech in BBA_TECHNOLOGIES:
        for speed in BBA_SPEEDS_MBIT:
            names.append(f"down_fn_hh_{tech}_{speed}")
            values.append(70.0 if tech == "ftthb" and speed <= 200 else 0.0)

    placeholders = ",".join("?" for _ in values)
    connection.execute(
        f'INSERT INTO "{BBA_GPKG_TABLE}" ({",".join(names)}) VALUES ({placeholders})',
        values,
    )
    connection.execute(
        f'INSERT INTO "{rtree}"(id,minx,maxx,miny,maxy) VALUES(?,?,?,?,?)',
        (1, x - 50, x + 50, y - 50, y + 50),
    )
    connection.commit()
    connection.close()
    return path, longitude, latitude


def test_breitband_grid_lookup_preserves_percentage_semantics(tmp_path) -> None:
    path, longitude, latitude = _grid_fixture(tmp_path)

    with BroadbandGridLookup(path) as lookup:
        assert lookup.row_count == 1
        evidence = lookup.lookup(longitude=longitude, latitude=latitude)

    assert evidence is not None
    assert evidence.source_cell_id == "100mNTESTE0001"
    assert evidence.coverage_at(100) == 100.0
    assert evidence.coverage_at(200) == 82.5
    assert evidence.max_full_download_mbps == 100
    assert evidence.max_any_download_mbps == 400
    assert evidence.max_any_coverage_percent == 25.0
    assert evidence.technology_coverage_by_speed["ftthb"][200] == 70.0


def test_breitband_grid_lookup_does_not_guess_outside_or_ambiguous_cell(tmp_path) -> None:
    path, longitude, latitude = _grid_fixture(tmp_path)

    with BroadbandGridLookup(path) as lookup:
        assert lookup.lookup(longitude=0.0, latitude=0.0) is None
        x, y = lookup.transformer.transform(longitude, latitude)

    rtree = f"rtree_{BBA_GPKG_TABLE}_geom"
    writable = sqlite3.connect(path)
    writable.execute(
        f'INSERT INTO "{rtree}"(id,minx,maxx,miny,maxy) VALUES(?,?,?,?,?)',
        (1, x - 1, x + 1, y - 1, y + 1),
    )
    writable.commit()
    writable.close()

    with BroadbandGridLookup(path) as lookup:
        assert lookup.lookup(longitude=longitude, latitude=latitude) is None


def test_postal_centroid_methods_are_never_precise_enough_for_100m_grid() -> None:
    assert property_location_precise_enough("postal_place_mean") is False
    assert property_location_precise_enough("address_mean") is False
    assert property_location_precise_enough(None) is False
    assert property_location_precise_enough("source_exact_point") is True


def test_starlink_fallback_requires_established_fixed_minimum() -> None:
    assert starlink_fallback_reason(None, minimum_download_mbps=100) == "fixed_unknown"
    assert starlink_fallback_reason(None, minimum_download_mbps=None) == "fixed_unknown"
