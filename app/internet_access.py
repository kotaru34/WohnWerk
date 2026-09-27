from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from geoalchemy2 import Geometry
from pyproj import Transformer
from shapely import Point, from_wkb
from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base
from app.models import Property
from app.property_location import internet_location_is_precise

BBA_SOURCE_NAME = "breitbandatlas-de-grid"
BBA_COUNTRY_CODE = "DE"
BBA_DATASET_DATE = date(2025, 12, 31)
BBA_SOURCE_URL = "https://gigabitgrundbuch.bund.de/GIGA/DE/Downloads_Suche/start.html"
BBA_ATTRIBUTION = "Breitbandatlas | Gigabit-Grundbuch"
BBA_EVIDENCE_PRECISION = "grid_100m"
BBA_SRS_ID = 25832
BBA_SPEED_CLASSES = (10, 16, 30, 50, 100, 200, 400, 1000)
BBA_TECHNOLOGIES = ("alle", "ftthb", "fttc", "ftth", "fttb", "hfc", "sonst")
BBA_TECH_LABELS_DE = {
    "alle": "Alle Technologien",
    "ftthb": "FTTH/FTTB",
    "fttc": "FTTC",
    "ftth": "FTTH",
    "fttb": "FTTB",
    "hfc": "HFC/Kabel",
    "sonst": "Sonstige",
}
STARLINK_RESIDENTIAL_URL = "https://www.starlink.com/residential"

_WGS84_TO_UTM32 = Transformer.from_crs(4326, BBA_SRS_ID, always_xy=True)


class InternetDatasetState(Base):
    """Published local source-cache state for broadband datasets."""

    __tablename__ = "internet_dataset_states"

    source_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    dataset_date: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(20), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1200), nullable=False)
    attribution: Mapped[str] = mapped_column(String(300), nullable=False)
    local_path: Mapped[str] = mapped_column(String(1200), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PropertyInternetEvidence(Base):
    """Source-backed broadband evidence for one canonical property."""

    __tablename__ = "property_internet_evidence"
    __table_args__ = (
        UniqueConstraint(
            "property_id",
            "source_name",
            name="uq_property_internet_evidence_property_source",
        ),
        Index("ix_property_internet_evidence_source_raster", "source_name", "raster_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_name: Mapped[str] = mapped_column(
        ForeignKey("internet_dataset_states.source_name", ondelete="CASCADE"),
        nullable=False,
    )
    dataset_date: Mapped[date] = mapped_column(Date, nullable=False)
    raster_id: Mapped[str] = mapped_column(String(32), nullable=False)
    municipality_ags: Mapped[str | None] = mapped_column(String(16))
    evidence_precision: Mapped[str] = mapped_column(String(40), nullable=False)
    lookup_location_method: Mapped[str] = mapped_column(String(40), nullable=False)
    max_grid_mbps: Mapped[int | None] = mapped_column(Integer)
    max_full_coverage_mbps: Mapped[int | None] = mapped_column(Integer)
    coverage_by_speed: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    coverage_by_technology: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def max_grid_coverage_pct(self) -> float | None:
        if self.max_grid_mbps is None:
            return None
        value = (self.coverage_by_speed or {}).get(str(self.max_grid_mbps))
        return float(value) if value is not None else None

    @property
    def technology_labels_de(self) -> tuple[str, ...]:
        labels: list[str] = []
        payload = self.coverage_by_technology or {}
        for technology in ("ftth", "fttb", "hfc", "fttc", "sonst"):
            values = payload.get(technology)
            if not isinstance(values, dict):
                continue
            available = [
                (int(speed), float(percent))
                for speed, percent in values.items()
                if percent is not None and float(percent) > 0
            ]
            if not available:
                continue
            speed, percent = max(available)
            labels.append(
                f"{BBA_TECH_LABELS_DE[technology]} bis {speed} Mbit/s "
                f"({percent:.0f}% Rasterhaushalte)"
            )
        return tuple(labels)


@dataclass(frozen=True, slots=True)
class BroadbandGridEvidence:
    raster_id: str
    municipality_ags: str | None
    coverage_by_speed: dict[str, float | None]
    coverage_by_technology: dict[str, dict[str, float | None]]
    max_grid_mbps: int | None
    max_full_coverage_mbps: int | None


@dataclass(frozen=True, slots=True)
class BroadbandDatasetDescriptor:
    table_name: str
    rtree_name: str


def _required_household_columns() -> tuple[str, ...]:
    return tuple(
        f"down_fn_hh_{technology}_{speed}"
        for technology in BBA_TECHNOLOGIES
        for speed in BBA_SPEED_CLASSES
    )


def _open_readonly(path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)


def _descriptor(connection: sqlite3.Connection) -> BroadbandDatasetDescriptor:
    rows = connection.execute(
        "select table_name, data_type, srs_id from gpkg_contents"
    ).fetchall()
    feature_rows = [row for row in rows if row[1] == "features"]
    if len(feature_rows) != 1:
        raise ValueError("Breitbandatlas GeoPackage must contain exactly one feature layer")

    table_name, _data_type, srs_id = feature_rows[0]
    geometry = connection.execute(
        "select column_name, geometry_type_name, srs_id "
        "from gpkg_geometry_columns where table_name=?",
        (table_name,),
    ).fetchone()
    if geometry is None:
        raise ValueError("Breitbandatlas GeoPackage has no geometry metadata")
    geometry_column, geometry_type, geometry_srs = geometry
    if geometry_column != "geom" or str(geometry_type).upper() != "POLYGON":
        raise ValueError("Breitbandatlas GeoPackage geometry must be POLYGON in column geom")
    if int(srs_id) != BBA_SRS_ID or int(geometry_srs) != BBA_SRS_ID:
        raise ValueError("Breitbandatlas GeoPackage must use EPSG:25832")

    columns = {
        row[1] for row in connection.execute(f'pragma table_info("{table_name}")').fetchall()
    }
    required = {"id", "geom", "raster_id", "raster_rowid", "ags", *_required_household_columns()}
    missing = sorted(required - columns)
    if missing:
        raise ValueError(f"Breitbandatlas GeoPackage is missing required columns: {missing!r}")

    rtree_name = f"rtree_{table_name}_geom"
    exists = connection.execute(
        "select 1 from sqlite_master where type='table' and name=?",
        (rtree_name,),
    ).fetchone()
    if exists is None:
        raise ValueError("Breitbandatlas GeoPackage has no geometry RTree index")

    bbox = connection.execute(
        f'select minx, maxx, miny, maxy from "{rtree_name}" order by id limit 1'
    ).fetchone()
    if bbox is None:
        raise ValueError("Breitbandatlas GeoPackage RTree is empty")
    width = float(bbox[1]) - float(bbox[0])
    height = float(bbox[3]) - float(bbox[2])
    if not (98 <= width <= 102 and 98 <= height <= 102):
        raise ValueError("Breitbandatlas grid is not approximately 100 x 100 metres")

    return BroadbandDatasetDescriptor(table_name=str(table_name), rtree_name=rtree_name)


def validate_breitbandatlas_gpkg(path: str | Path) -> BroadbandDatasetDescriptor:
    with _open_readonly(path) as connection:
        return _descriptor(connection)


def _gpkg_geometry_to_shape(payload: bytes | memoryview):
    data = bytes(payload)
    if len(data) < 8 or data[:2] != b"GP":
        raise ValueError("invalid GeoPackage geometry header")
    flags = data[3]
    envelope_code = (flags >> 1) & 0b111
    envelope_doubles = {0: 0, 1: 4, 2: 6, 3: 6, 4: 8}.get(envelope_code)
    if envelope_doubles is None:
        raise ValueError("unsupported GeoPackage geometry envelope")
    offset = 8 + envelope_doubles * 8
    if len(data) <= offset:
        raise ValueError("truncated GeoPackage geometry")
    return from_wkb(data[offset:])


def _derive_maxima(coverage_by_speed: dict[str, float | None]) -> tuple[int | None, int | None]:
    present = [
        speed
        for speed in BBA_SPEED_CLASSES
        if (coverage_by_speed.get(str(speed)) or 0.0) > 0
    ]
    full = [
        speed
        for speed in BBA_SPEED_CLASSES
        if coverage_by_speed.get(str(speed)) is not None
        and float(coverage_by_speed[str(speed)]) >= 99.999
    ]
    return (max(present) if present else None, max(full) if full else None)


def _row_to_evidence(row: sqlite3.Row) -> BroadbandGridEvidence:
    coverage_by_technology: dict[str, dict[str, float | None]] = {}
    for technology in BBA_TECHNOLOGIES:
        coverage_by_technology[technology] = {
            str(speed): (
                float(row[f"down_fn_hh_{technology}_{speed}"])
                if row[f"down_fn_hh_{technology}_{speed}"] is not None
                else None
            )
            for speed in BBA_SPEED_CLASSES
        }
    coverage_by_speed = dict(coverage_by_technology["alle"])
    max_grid_mbps, max_full_coverage_mbps = _derive_maxima(coverage_by_speed)
    return BroadbandGridEvidence(
        raster_id=str(row["raster_id"]),
        municipality_ags=str(row["ags"]) if row["ags"] is not None else None,
        coverage_by_speed=coverage_by_speed,
        coverage_by_technology=coverage_by_technology,
        max_grid_mbps=max_grid_mbps,
        max_full_coverage_mbps=max_full_coverage_mbps,
    )


def lookup_breitbandatlas_grid(
    path: str | Path,
    *,
    longitude: float,
    latitude: float,
) -> BroadbandGridEvidence | None:
    x, y = _WGS84_TO_UTM32.transform(longitude, latitude)
    with _open_readonly(path) as connection:
        connection.row_factory = sqlite3.Row
        descriptor = _descriptor(connection)
        columns = ["raster_id", "ags", "geom", *_required_household_columns()]
        sql = (
            "select "
            + ",".join(f'f."{column}"' for column in columns)
            + f' from "{descriptor.table_name}" f '
            + f'join "{descriptor.rtree_name}" r on r.id=f.id '
            + "where r.minx<=? and r.maxx>=? and r.miny<=? and r.maxy>=?"
        )
        candidates = connection.execute(sql, (x, x, y, y)).fetchall()

    point = Point(x, y)
    matched = [
        row for row in candidates if _gpkg_geometry_to_shape(row["geom"]).covers(point)
    ]
    if not matched:
        return None
    matched.sort(key=lambda row: str(row["raster_id"]))
    return _row_to_evidence(matched[0])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish_breitbandatlas_cache(
    session: Session,
    source_path: str | Path,
    *,
    cache_dir: str | Path,
    dataset_date: date = BBA_DATASET_DATE,
) -> Path:
    source = Path(source_path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"Breitbandatlas source file does not exist: {source}")
    validate_breitbandatlas_gpkg(source)
    source_sha256 = _sha256_file(source)

    destination_dir = Path(cache_dir).expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"breitbandatlas-de-{dataset_date.isoformat()}.gpkg"
    temporary = destination.with_suffix(".gpkg.tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        shutil.copyfile(source, temporary)
        validate_breitbandatlas_gpkg(temporary)
        os.replace(temporary, destination)
        destination.chmod(0o644)
    finally:
        if temporary.exists():
            temporary.unlink()

    row = session.get(InternetDatasetState, BBA_SOURCE_NAME)
    if row is None:
        row = InternetDatasetState(
            source_name=BBA_SOURCE_NAME,
            country_code=BBA_COUNTRY_CODE,
            dataset_date=dataset_date,
            coverage_status="ok",
            source_url=BBA_SOURCE_URL,
            attribution=BBA_ATTRIBUTION,
            local_path=str(destination),
            source_sha256=source_sha256,
        )
        session.add(row)
    else:
        row.country_code = BBA_COUNTRY_CODE
        row.dataset_date = dataset_date
        row.coverage_status = "ok"
        row.source_url = BBA_SOURCE_URL
        row.attribution = BBA_ATTRIBUTION
        row.local_path = str(destination)
        row.source_sha256 = source_sha256
        row.imported_at = func.now()
    session.commit()
    return destination


def internet_dataset_ready(session: Session, *, country_code: str = "DE") -> bool:
    if country_code != BBA_COUNTRY_CODE:
        return False
    state = session.get(InternetDatasetState, BBA_SOURCE_NAME)
    return bool(
        state is not None
        and state.coverage_status == "ok"
        and Path(state.local_path).is_file()
    )


def enrich_precise_properties_from_breitbandatlas(
    session: Session,
    *,
    property_ids: set[int] | None = None,
) -> tuple[int, int]:
    state = session.get(InternetDatasetState, BBA_SOURCE_NAME)
    if state is None or state.coverage_status != "ok":
        raise RuntimeError("German Breitbandatlas dataset is not published")
    path = Path(state.local_path)
    validate_breitbandatlas_gpkg(path)

    geometry = cast(Property.location, Geometry(geometry_type="POINT", srid=4326))
    statement = select(
        Property.id,
        Property.location_method,
        func.ST_X(geometry).label("longitude"),
        func.ST_Y(geometry).label("latitude"),
    ).where(
        Property.location.is_not(None),
        Property.location_method.is_not(None),
    )
    if property_ids is not None:
        statement = statement.where(Property.id.in_(property_ids))

    rows = session.execute(statement).mappings().all()
    eligible = [row for row in rows if internet_location_is_precise(row["location_method"])]
    updated = 0
    no_grid = 0
    for row in eligible:
        evidence = lookup_breitbandatlas_grid(
            path,
            longitude=float(row["longitude"]),
            latitude=float(row["latitude"]),
        )
        existing = session.scalar(
            select(PropertyInternetEvidence).where(
                PropertyInternetEvidence.property_id == int(row["id"]),
                PropertyInternetEvidence.source_name == BBA_SOURCE_NAME,
            )
        )
        if evidence is None:
            no_grid += 1
            if existing is not None:
                session.delete(existing)
            continue

        if existing is None:
            existing = PropertyInternetEvidence(
                property_id=int(row["id"]),
                source_name=BBA_SOURCE_NAME,
                dataset_date=state.dataset_date,
                raster_id=evidence.raster_id,
                municipality_ags=evidence.municipality_ags,
                evidence_precision=BBA_EVIDENCE_PRECISION,
                lookup_location_method=str(row["location_method"]),
                max_grid_mbps=evidence.max_grid_mbps,
                max_full_coverage_mbps=evidence.max_full_coverage_mbps,
                coverage_by_speed=evidence.coverage_by_speed,
                coverage_by_technology=evidence.coverage_by_technology,
            )
            session.add(existing)
        else:
            existing.dataset_date = state.dataset_date
            existing.raster_id = evidence.raster_id
            existing.municipality_ags = evidence.municipality_ags
            existing.evidence_precision = BBA_EVIDENCE_PRECISION
            existing.lookup_location_method = str(row["location_method"])
            existing.max_grid_mbps = evidence.max_grid_mbps
            existing.max_full_coverage_mbps = evidence.max_full_coverage_mbps
            existing.coverage_by_speed = evidence.coverage_by_speed
            existing.coverage_by_technology = evidence.coverage_by_technology
        updated += 1

    session.commit()
    return updated, no_grid


def load_property_internet_evidence(
    session: Session,
    property_ids: set[int],
    *,
    country_code: str,
) -> dict[int, PropertyInternetEvidence]:
    if country_code != BBA_COUNTRY_CODE or not property_ids:
        return {}
    rows = session.scalars(
        select(PropertyInternetEvidence).where(
            PropertyInternetEvidence.property_id.in_(property_ids),
            PropertyInternetEvidence.source_name == BBA_SOURCE_NAME,
        )
    )
    return {row.property_id: row for row in rows}


def starlink_fallback_recommended(
    evidence: PropertyInternetEvidence | None,
    *,
    minimum_fixed_mbps: int | None,
) -> bool:
    if evidence is None:
        return True
    if minimum_fixed_mbps is None:
        return False
    return (
        evidence.max_full_coverage_mbps is None
        or evidence.max_full_coverage_mbps < minimum_fixed_mbps
    )
