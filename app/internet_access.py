from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Self

from geoalchemy2 import Geometry
from pyproj import Transformer
from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    cast,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base
from app.models import Property

BBA_SOURCE_NAME = "breitbandatlas-gigabit-grundbuch"
BBA_COUNTRY_CODE = "DE"
BBA_DATASET_DATE = date(2025, 12, 31)
BBA_SOURCE_URL = "https://gigabitgrundbuch.bund.de/GIGA/DE/Breitbandatlas/Downloads/start.html"
BBA_ATTRIBUTION = "Breitbandatlas | Gigabit-Grundbuch (https://gigabitgrundbuch.bund.de)"
BBA_EVIDENCE_PRECISION = "grid_100m"
BBA_GPKG_EPSG = 25832
BBA_GPKG_TABLE = "Versorgungsdaten_Gitterzellen_Stand_20251231"
BBA_SPEEDS_MBIT = (10, 16, 30, 50, 100, 200, 400, 1000)
BBA_TECHNOLOGIES = {
    "ftthb": "FTTH/FTTB",
    "ftth": "FTTH",
    "fttb": "FTTB",
    "fttc": "FTTC",
    "hfc": "HFC/Kabel",
    "sonst": "Sonstige",
}

# Only methods with an explicit point/address contract may enter a 100 m source cell.
# Existing DE/AT postal centroids deliberately do not qualify.
PRECISE_PROPERTY_LOCATION_METHODS = frozenset(
    {
        "source_exact_point",
        "source_address_point",
        "address_geocode_rooftop",
    }
)
COARSE_PROPERTY_LOCATION_METHODS = frozenset({"postal_place_mean", "address_mean"})

STARLINK_DE_SOURCE_URL = "https://starlink.com/de/residential"
STARLINK_DE_SNAPSHOT_DATE = date(2026, 9, 27)
STARLINK_DE_FROM_EUR_MONTH = Decimal(35)
STARLINK_DE_MAX_LABEL = "bis 400+ Mbit/s"


class InternetDatasetState(Base):
    """Completeness/provenance marker for a broadband reference snapshot."""

    __tablename__ = "internet_dataset_states"

    source_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    dataset_date: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(20), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1200), nullable=False)
    source_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_precision: Mapped[str] = mapped_column(String(40), nullable=False)
    attribution: Mapped[str | None] = mapped_column(String(500))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PropertyInternetEvidence(Base):
    """Compact source-backed broadband evidence for one sufficiently precise house point."""

    __tablename__ = "property_internet_evidence"
    __table_args__ = (
        UniqueConstraint(
            "property_id",
            "source_name",
            name="uq_property_internet_evidence_property_source",
        ),
        Index("ix_property_internet_evidence_country_source", "country_code", "source_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_name: Mapped[str] = mapped_column(
        ForeignKey("internet_dataset_states.source_name", ondelete="CASCADE"), nullable=False
    )
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    dataset_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_cell_id: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_precision: Mapped[str] = mapped_column(String(40), nullable=False)
    location_method: Mapped[str] = mapped_column(String(80), nullable=False)
    max_any_download_mbps: Mapped[int | None] = mapped_column(Integer)
    max_any_coverage_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    max_full_download_mbps: Mapped[int | None] = mapped_column(Integer)
    coverage_by_speed: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    technology_coverage_by_speed: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


@dataclass(frozen=True, slots=True)
class BroadbandCellEvidence:
    source_cell_id: str
    ags: str | None
    coverage_by_speed: dict[int, float | None]
    technology_coverage_by_speed: dict[str, dict[int, float | None]]

    @property
    def max_any_download_mbps(self) -> int | None:
        values = [
            speed
            for speed, percent in self.coverage_by_speed.items()
            if percent is not None and percent > 0
        ]
        return max(values, default=None)

    @property
    def max_any_coverage_percent(self) -> float | None:
        speed = self.max_any_download_mbps
        return self.coverage_by_speed.get(speed) if speed is not None else None

    @property
    def max_full_download_mbps(self) -> int | None:
        values = [
            speed
            for speed, percent in self.coverage_by_speed.items()
            if percent is not None and percent >= 99.999
        ]
        return max(values, default=None)

    def coverage_at(self, speed_mbps: int) -> float | None:
        return self.coverage_by_speed.get(speed_mbps)


@dataclass(frozen=True, slots=True)
class InternetAccess:
    property_id: int
    source_cell_id: str
    dataset_date: date
    evidence_precision: str
    location_method: str
    max_any_download_mbps: int | None
    max_any_coverage_percent: float | None
    max_full_download_mbps: int | None
    coverage_by_speed: dict[int, float | None]
    technology_coverage_by_speed: dict[str, dict[int, float | None]]

    def coverage_at(self, speed_mbps: int) -> float | None:
        return self.coverage_by_speed.get(speed_mbps)

    def minimum_established(self, speed_mbps: int | None) -> bool:
        if speed_mbps is None:
            return self.max_any_download_mbps is not None
        percent = self.coverage_at(speed_mbps)
        return percent is not None and percent >= 99.999

    @property
    def technology_labels_de(self) -> tuple[str, ...]:
        labels: list[str] = []
        speed = self.max_any_download_mbps
        if speed is None:
            return ()
        for key, label in BBA_TECHNOLOGIES.items():
            percent = self.technology_coverage_by_speed.get(key, {}).get(speed)
            if percent is not None and percent > 0:
                labels.append(f"{label} {percent:.0f} %")
        return tuple(labels)


class BroadbandGridLookup:
    """Read one official Bundesnetzagentur 100 m grid cell from a GeoPackage."""

    def __init__(
        self,
        path: str | Path,
        *,
        table_name: str = BBA_GPKG_TABLE,
    ) -> None:
        self.path = Path(path)
        self.table_name = table_name
        uri = f"file:{self.path.as_posix()}?mode=ro"
        self.connection = sqlite3.connect(uri, uri=True)
        self.connection.row_factory = sqlite3.Row
        self.transformer = Transformer.from_crs(4326, BBA_GPKG_EPSG, always_xy=True)
        self._validate()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    @property
    def row_count(self) -> int:
        return int(
            self.connection.execute(
                f'SELECT COUNT(*) FROM "{self.table_name}"'
            ).fetchone()[0]
        )

    def _validate(self) -> None:
        row = self.connection.execute(
            "SELECT data_type, srs_id FROM gpkg_contents WHERE table_name = ?",
            (self.table_name,),
        ).fetchone()
        if row is None or row["data_type"] != "features" or int(row["srs_id"]) != BBA_GPKG_EPSG:
            raise ValueError("unexpected Breitbandatlas GeoPackage layer or CRS")
        columns = {
            str(row["name"])
            for row in self.connection.execute(
                f'PRAGMA table_info("{self.table_name}")'
            )
        }
        required = {"id", "geom", "raster_id", "ags"}
        required.update(f"down_fn_hh_alle_{speed}" for speed in BBA_SPEEDS_MBIT)
        for tech in BBA_TECHNOLOGIES:
            required.update(f"down_fn_hh_{tech}_{speed}" for speed in BBA_SPEEDS_MBIT)
        missing = required - columns
        if missing:
            raise ValueError(
                "Breitbandatlas GeoPackage missing required columns: "
                + ", ".join(sorted(missing))
            )
        rtree = f"rtree_{self.table_name}_geom"
        if (
            self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
                (rtree,),
            ).fetchone()
            is None
        ):
            raise ValueError("Breitbandatlas GeoPackage has no expected spatial index")

    @staticmethod
    def _percent(value: object | None) -> float | None:
        if value is None:
            return None
        percent = float(value)
        if not 0 <= percent <= 100:
            raise ValueError(f"invalid Breitbandatlas coverage percentage: {percent}")
        return percent

    def lookup(self, *, longitude: float, latitude: float) -> BroadbandCellEvidence | None:
        x, y = self.transformer.transform(longitude, latitude)
        rtree = f"rtree_{self.table_name}_geom"
        requested_columns = ["raster_id", "ags"]
        requested_columns.extend(
            f"down_fn_hh_alle_{speed}" for speed in BBA_SPEEDS_MBIT
        )
        for tech in BBA_TECHNOLOGIES:
            requested_columns.extend(
                f"down_fn_hh_{tech}_{speed}" for speed in BBA_SPEEDS_MBIT
            )
        projection = ", ".join(f'f."{name}"' for name in requested_columns)
        rows = self.connection.execute(
            (
                f'SELECT {projection} FROM "{rtree}" r '
                f'JOIN "{self.table_name}" f ON f.id = r.id '
                "WHERE r.minx <= ? AND r.maxx >= ? AND r.miny <= ? AND r.maxy >= ? "
                "ORDER BY f.id LIMIT 2"
            ),
            (x, x, y, y),
        ).fetchall()
        if len(rows) != 1:
            return None
        row = rows[0]
        coverage = {
            speed: self._percent(row[f"down_fn_hh_alle_{speed}"])
            for speed in BBA_SPEEDS_MBIT
        }
        technologies = {
            tech: {
                speed: self._percent(row[f"down_fn_hh_{tech}_{speed}"])
                for speed in BBA_SPEEDS_MBIT
            }
            for tech in BBA_TECHNOLOGIES
        }
        return BroadbandCellEvidence(
            source_cell_id=str(row["raster_id"]),
            ags=str(row["ags"]) if row["ags"] is not None else None,
            coverage_by_speed=coverage,
            technology_coverage_by_speed=technologies,
        )


def property_location_precise_enough(method: str | None) -> bool:
    return bool(method and method in PRECISE_PROPERTY_LOCATION_METHODS)


def internet_dataset_ready(session: Session, *, country_code: str = "DE") -> bool:
    return bool(
        session.scalar(
            select(InternetDatasetState.coverage_status).where(
                InternetDatasetState.source_name == BBA_SOURCE_NAME,
                InternetDatasetState.country_code == country_code,
            )
        )
        == "ok"
    )


def _json_speed_map(values: dict[int, float | None]) -> dict[str, float | None]:
    return {str(speed): percent for speed, percent in values.items()}


def _read_speed_map(values: dict | None) -> dict[int, float | None]:
    return {
        int(speed): (float(percent) if percent is not None else None)
        for speed, percent in (values or {}).items()
    }


def publish_breitbandatlas_evidence(
    session: Session,
    *,
    gpkg_path: str | Path,
    dataset_date: date = BBA_DATASET_DATE,
    source_url: str = BBA_SOURCE_URL,
) -> tuple[int, int]:
    """Atomically refresh compact evidence for precise DE properties only."""

    with BroadbandGridLookup(gpkg_path) as lookup:
        row_count = lookup.row_count
        if row_count <= 0:
            raise ValueError("refusing to publish an empty Breitbandatlas snapshot")

        state_insert = pg_insert(InternetDatasetState).values(
            source_name=BBA_SOURCE_NAME,
            country_code=BBA_COUNTRY_CODE,
            dataset_date=dataset_date,
            coverage_status="importing",
            source_url=source_url,
            source_row_count=row_count,
            evidence_precision=BBA_EVIDENCE_PRECISION,
            attribution=BBA_ATTRIBUTION,
        )
        session.execute(
            state_insert.on_conflict_do_update(
                index_elements=[InternetDatasetState.source_name],
                set_={
                    "country_code": BBA_COUNTRY_CODE,
                    "dataset_date": dataset_date,
                    "coverage_status": "importing",
                    "source_url": source_url,
                    "source_row_count": row_count,
                    "evidence_precision": BBA_EVIDENCE_PRECISION,
                    "attribution": BBA_ATTRIBUTION,
                    "imported_at": func.now(),
                },
            )
        )

        geometry = cast(Property.location, Geometry(geometry_type="POINT", srid=4326))
        properties = list(
            session.execute(
                select(
                    Property.id,
                    Property.location_method,
                    func.ST_X(geometry).label("longitude"),
                    func.ST_Y(geometry).label("latitude"),
                ).where(
                    Property.location.is_not(None),
                    Property.location_method.in_(PRECISE_PROPERTY_LOCATION_METHODS),
                    Property.postal_code.is_not(None),
                    func.length(Property.postal_code) == 5,
                )
            )
        )

        matched_ids: set[int] = set()
        for property_id, location_method, longitude, latitude in properties:
            evidence = lookup.lookup(
                longitude=float(longitude),
                latitude=float(latitude),
            )
            if evidence is None:
                continue
            property_id = int(property_id)
            matched_ids.add(property_id)
            values = {
                "property_id": property_id,
                "source_name": BBA_SOURCE_NAME,
                "country_code": BBA_COUNTRY_CODE,
                "dataset_date": dataset_date,
                "source_cell_id": evidence.source_cell_id,
                "evidence_precision": BBA_EVIDENCE_PRECISION,
                "location_method": str(location_method),
                "max_any_download_mbps": evidence.max_any_download_mbps,
                "max_any_coverage_percent": evidence.max_any_coverage_percent,
                "max_full_download_mbps": evidence.max_full_download_mbps,
                "coverage_by_speed": _json_speed_map(evidence.coverage_by_speed),
                "technology_coverage_by_speed": {
                    tech: _json_speed_map(speed_map)
                    for tech, speed_map in evidence.technology_coverage_by_speed.items()
                },
            }
            statement = pg_insert(PropertyInternetEvidence).values(**values)
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        PropertyInternetEvidence.property_id,
                        PropertyInternetEvidence.source_name,
                    ],
                    set_={
                        key: getattr(statement.excluded, key)
                        for key in values
                        if key not in {"property_id", "source_name"}
                    }
                    | {"updated_at": func.now()},
                )
            )

        stale = [
            condition
            for condition in [
                PropertyInternetEvidence.source_name == BBA_SOURCE_NAME,
                (
                    PropertyInternetEvidence.property_id.not_in(matched_ids)
                    if matched_ids
                    else None
                ),
            ]
            if condition is not None
        ]
        session.execute(delete(PropertyInternetEvidence).where(*stale))

        ready = pg_insert(InternetDatasetState).values(
            source_name=BBA_SOURCE_NAME,
            country_code=BBA_COUNTRY_CODE,
            dataset_date=dataset_date,
            coverage_status="ok",
            source_url=source_url,
            source_row_count=row_count,
            evidence_precision=BBA_EVIDENCE_PRECISION,
            attribution=BBA_ATTRIBUTION,
        )
        session.execute(
            ready.on_conflict_do_update(
                index_elements=[InternetDatasetState.source_name],
                set_={
                    "country_code": BBA_COUNTRY_CODE,
                    "dataset_date": dataset_date,
                    "coverage_status": "ok",
                    "source_url": source_url,
                    "source_row_count": row_count,
                    "evidence_precision": BBA_EVIDENCE_PRECISION,
                    "attribution": BBA_ATTRIBUTION,
                    "imported_at": func.now(),
                },
            )
        )
        session.commit()
        return row_count, len(matched_ids)


def load_property_internet_access(
    session: Session,
    property_ids: set[int],
) -> dict[int, InternetAccess]:
    if not property_ids or not internet_dataset_ready(session):
        return {}
    rows = session.scalars(
        select(PropertyInternetEvidence).where(
            PropertyInternetEvidence.property_id.in_(property_ids),
            PropertyInternetEvidence.source_name == BBA_SOURCE_NAME,
        )
    )
    return {
        row.property_id: InternetAccess(
            property_id=row.property_id,
            source_cell_id=row.source_cell_id,
            dataset_date=row.dataset_date,
            evidence_precision=row.evidence_precision,
            location_method=row.location_method,
            max_any_download_mbps=row.max_any_download_mbps,
            max_any_coverage_percent=(
                float(row.max_any_coverage_percent)
                if row.max_any_coverage_percent is not None
                else None
            ),
            max_full_download_mbps=row.max_full_download_mbps,
            coverage_by_speed=_read_speed_map(row.coverage_by_speed),
            technology_coverage_by_speed={
                tech: _read_speed_map(speed_map)
                for tech, speed_map in (row.technology_coverage_by_speed or {}).items()
            },
        )
        for row in rows
    }


def starlink_fallback_reason(
    access: InternetAccess | None,
    *,
    minimum_download_mbps: int | None,
) -> str | None:
    if access is None:
        return "fixed_unknown"
    if minimum_download_mbps is None:
        return None
    if not access.minimum_established(minimum_download_mbps):
        return "minimum_not_established"
    return None
