from __future__ import annotations

import csv
import math
from collections import defaultdict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path
from typing import TextIO
from zipfile import ZipFile

from geoalchemy2.elements import WKTElement
from pyproj import Transformer
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import PostalCode

BEV_LOCATION_SOURCE = "BEV Adressregister Stichtagsdaten"
BEV_LOCATION_METHOD = "address_mean"
BEV_SUPPORTED_EPSG = frozenset({31254, 31255, 31256})


@dataclass(slots=True)
class ProjectedAccumulator:
    sum_x: float = 0.0
    sum_y: float = 0.0
    count: int = 0

    def add(self, x: float, y: float) -> None:
        self.sum_x += x
        self.sum_y += y
        self.count += 1


@dataclass(frozen=True, slots=True)
class PostalCentroid:
    postal_code: str
    longitude: float
    latitude: float
    sample_count: int


@contextmanager
def open_bev_address_csv(source: Path) -> Iterator[TextIO]:
    """Open ADRESSE.csv from a BEV snapshot ZIP or an extracted CSV file."""
    if source.suffix.casefold() != ".zip":
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            yield handle
        return

    with ZipFile(source) as archive:
        address_members = [
            name for name in archive.namelist() if Path(name).name.casefold() == "adresse.csv"
        ]
        if not address_members:
            raise ValueError(f"No ADRESSE.csv found in {source}")
        if len(address_members) > 1:
            raise ValueError(f"Multiple ADRESSE.csv files found in {source}")

        with archive.open(address_members[0], "r") as binary_handle:
            text_handle = TextIOWrapper(binary_handle, encoding="utf-8-sig", newline="")
            try:
                yield text_handle
            finally:
                text_handle.detach()


def _parse_coordinate(row: dict[str, str], field: str) -> float | None:
    raw_value = (row.get(field) or "").strip()
    if not raw_value or "#" in raw_value:
        return None

    try:
        value = float(raw_value)
    except ValueError:
        return None

    return value if math.isfinite(value) else None


def _parse_epsg(row: dict[str, str]) -> int | None:
    raw_value = (row.get("EPSG") or "").strip()
    try:
        epsg = int(raw_value)
    except ValueError:
        return None
    return epsg if epsg in BEV_SUPPORTED_EPSG else None


def aggregate_projected_addresses(
    rows: Iterable[dict[str, str]],
) -> dict[tuple[str, int], ProjectedAccumulator]:
    """Aggregate address coordinates before projection to keep the import lightweight."""
    buckets: dict[tuple[str, int], ProjectedAccumulator] = defaultdict(ProjectedAccumulator)

    for row in rows:
        postal_code = (row.get("PLZ") or "").strip()
        if len(postal_code) != 4 or not postal_code.isdigit():
            continue

        x = _parse_coordinate(row, "RW")
        y = _parse_coordinate(row, "HW")
        epsg = _parse_epsg(row)
        if x is None or y is None or epsg is None:
            continue

        buckets[(postal_code, epsg)].add(x, y)

    return dict(buckets)


def projected_buckets_to_centroids(
    buckets: dict[tuple[str, int], ProjectedAccumulator],
) -> list[PostalCentroid]:
    """Transform per-zone address means to WGS84 and combine them per postal code."""
    transformers = {
        epsg: Transformer.from_crs(epsg, 4326, always_xy=True) for epsg in BEV_SUPPORTED_EPSG
    }
    weighted: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])

    for (postal_code, epsg), bucket in buckets.items():
        if bucket.count <= 0:
            continue

        mean_x = bucket.sum_x / bucket.count
        mean_y = bucket.sum_y / bucket.count
        longitude, latitude = transformers[epsg].transform(mean_x, mean_y)
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            continue

        target = weighted[postal_code]
        target[0] += longitude * bucket.count
        target[1] += latitude * bucket.count
        target[2] += bucket.count

    centroids: list[PostalCentroid] = []
    for postal_code, (weighted_lon, weighted_lat, raw_count) in weighted.items():
        sample_count = int(raw_count)
        if sample_count <= 0:
            continue
        centroids.append(
            PostalCentroid(
                postal_code=postal_code,
                longitude=weighted_lon / sample_count,
                latitude=weighted_lat / sample_count,
                sample_count=sample_count,
            )
        )

    return sorted(centroids, key=lambda item: item.postal_code)


def parse_bev_postal_centroids(handle: TextIO) -> list[PostalCentroid]:
    reader = csv.DictReader(handle, delimiter=";")
    required = {"PLZ", "RW", "HW", "EPSG"}
    actual = set(reader.fieldnames or ())
    missing = required - actual
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"BEV ADRESSE.csv is missing required fields: {missing_list}")

    return projected_buckets_to_centroids(aggregate_projected_addresses(reader))


def load_bev_postal_centroids(source: Path) -> list[PostalCentroid]:
    with open_bev_address_csv(source) as handle:
        return parse_bev_postal_centroids(handle)


def update_postal_centroids(session: Session, centroids: Iterable[PostalCentroid]) -> int:
    """Update existing RTR postal-code rows with BEV-derived approximate locations."""
    updated = 0

    for centroid in centroids:
        statement = (
            update(PostalCode)
            .where(PostalCode.postal_code == centroid.postal_code)
            .values(
                location=WKTElement(
                    f"POINT({centroid.longitude:.8f} {centroid.latitude:.8f})",
                    srid=4326,
                ),
                location_source=BEV_LOCATION_SOURCE,
                location_method=BEV_LOCATION_METHOD,
                location_sample_count=centroid.sample_count,
            )
        )
        result = session.execute(statement)
        updated += result.rowcount or 0

    session.commit()
    return updated
