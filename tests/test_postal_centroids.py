from __future__ import annotations

from io import StringIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pyproj import Transformer

from app.postal_centroids import load_bev_postal_centroids, parse_bev_postal_centroids


def bev_row(postal_code: str, longitude: float, latitude: float) -> str:
    to_bev = Transformer.from_crs(4326, 31256, always_xy=True)
    x, y = to_bev.transform(longitude, latitude)
    return f"{postal_code};{x:.2f};{y:.2f};31256"


def test_parse_bev_postal_centroids() -> None:
    payload = "\n".join(
        [
            "PLZ;RW;HW;EPSG",
            bev_row("1010", 16.3700, 48.2080),
            bev_row("1010", 16.3720, 48.2100),
            bev_row("1020", 16.4000, 48.2150),
            "9999;#;#;31256",
        ]
    )

    records = parse_bev_postal_centroids(StringIO(payload))

    assert [record.postal_code for record in records] == ["1010", "1020"]
    vienna = records[0]
    assert vienna.sample_count == 2
    assert vienna.longitude == pytest.approx(16.3710, abs=0.001)
    assert vienna.latitude == pytest.approx(48.2090, abs=0.001)


def test_load_centroids_from_nested_snapshot_zip(tmp_path) -> None:
    payload = "\n".join(
        [
            "PLZ;RW;HW;EPSG",
            bev_row("1010", 16.3700, 48.2080),
        ]
    )
    archive_path = tmp_path / "bev.zip"

    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("snapshot/ADRESSE.csv", payload)

    records = load_bev_postal_centroids(archive_path)

    assert len(records) == 1
    assert records[0].postal_code == "1010"
    assert records[0].sample_count == 1


def test_missing_required_bev_columns_fail() -> None:
    with pytest.raises(ValueError, match="missing required fields"):
        parse_bev_postal_centroids(StringIO("PLZ;RW\n1010;1\n"))
