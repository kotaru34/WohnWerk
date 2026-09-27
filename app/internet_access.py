from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
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
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base
from app.models import ListingStatus, Property, PropertyListing, Source

BBA_SOURCE_NAME = "breitbandatlas-de-grid"
BBA_COUNTRY_CODE = "DE"
BBA_DATASET_DATE = date(2025, 12, 31)
BBA_SOURCE_URL = "https://gigabitgrundbuch.bund.de/GIGA/DE/Downloads_Suche/start.html"
BBA_ATTRIBUTION = "Breitbandatlas | Gigabit-Grundbuch"
BBA_RASTER_SIZE_M = 100
BBA_SPEED_CLASSES = (10, 16, 30, 50, 100, 200, 400, 1000)
BBA_TECHNOLOGIES = ("alle", "fttb", "fttc", "ftth", "ftthb", "hfc", "sonst")
BBA_HOUSEHOLD_PREFIX = "down_fn_hh_"
BBA_FULL_COVERAGE_PERCENT = Decimal("99.999")

IMMO_TELEKOM_SOURCE_NAME = "immoscout24-telekom"
IMMO_SOURCE_NAME = "immoscout24-de"
IMMO_PROVIDER_NAME = "Telekom"
IMMO_DETAIL_RECHECK_HOURS = 24
IMMO_DETAIL_TIMEOUT_SECONDS = 10.0

STARLINK_NAME = "Starlink"
STARLINK_URL = "https://www.starlink.com/residential"

LOCATION_PRECISION_POSTAL_CENTROID = "postal_centroid"
LOCATION_PRECISION_SOURCE_EXACT = "source_exact_coordinate"
LOCATION_PRECISION_EXACT_GEOCODE = "source_exact_address_geocode"
INTERNET_GRID_ELIGIBLE_LOCATION_PRECISIONS = {
    LOCATION_PRECISION_SOURCE_EXACT,
    LOCATION_PRECISION_EXACT_GEOCODE,
}

_AVAILABILITY_RE = re.compile(r'"obj_telekomInternetAvailable"\s*:\s*"?(true|false)"?', re.I)
_SPEED_RE = re.compile(r'"obj_telekomInternetSpeed"\s*:\s*"(?P<speed>\d+)\s*MBit/s"', re.I)
_SCOUT_ID_RE = re.compile(r'"obj_scoutId"\s*:\s*"(?P<id>\d+)"', re.I)
_PROVIDER_URL_RE = re.compile(
    r'"obj_telekomInternetUrlBase"\s*:\s*"(?P<url>https?://[^"]+)"',
    re.I,
)


class InternetDatasetState(Base):
    """Completeness/provenance marker for one external Internet dataset artifact."""

    __tablename__ = "internet_dataset_states"

    source_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    dataset_date: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(20), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1200), nullable=False)
    attribution: Mapped[str] = mapped_column(String(300), nullable=False)
    evidence_precision: Mapped[str] = mapped_column(String(40), nullable=False)
    artifact_path: Mapped[str | None] = mapped_column(String(1200))
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    feature_count: Mapped[int | None] = mapped_column(Integer)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PropertyInternetEvidence(Base):
    """One source-backed Internet observation for a canonical property."""

    __tablename__ = "property_internet_evidence"
    __table_args__ = (
        UniqueConstraint(
            "property_id",
            "source_name",
            "source_reference",
            name="uq_property_internet_evidence_source_reference",
        ),
        Index(
            "ix_property_internet_evidence_property_source",
            "property_id",
            "source_name",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    source_name: Mapped[str] = mapped_column(String(80), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_precision: Mapped[str] = mapped_column(String(60), nullable=False)
    provider_name: Mapped[str | None] = mapped_column(String(160))
    availability_state: Mapped[str] = mapped_column(String(20), nullable=False)
    max_download_mbps: Mapped[int | None] = mapped_column(Integer)
    technology: Mapped[str | None] = mapped_column(String(80))
    coverage_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    monthly_price_eur: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    source_url: Mapped[str] = mapped_column(String(1200), nullable=False)
    dataset_date: Mapped[date | None] = mapped_column(Date)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


@dataclass(frozen=True, slots=True)
class ImmoScoutTelekomInternet:
    scout_id: str
    availability_state: str
    max_download_mbps: int | None
    provider_url: str | None


@dataclass(frozen=True, slots=True)
class BroadbandGridCell:
    raster_id: str
    ags: str | None
    coverage_all: dict[int, Decimal | None]
    coverage_by_technology: dict[str, dict[int, Decimal | None]]

    @property
    def max_defensible_download_mbps(self) -> int | None:
        values = [
            speed
            for speed, percent in self.coverage_all.items()
            if percent is not None and percent >= BBA_FULL_COVERAGE_PERCENT
        ]
        return max(values) if values else None


@dataclass(frozen=True, slots=True)
class InternetEvidenceView:
    source_name: str
    source_reference: str
    evidence_kind: str
    evidence_precision: str
    provider_name: str | None
    availability_state: str
    max_download_mbps: int | None
    technology: str | None
    coverage_percent: Decimal | None
    monthly_price_eur: Decimal | None
    source_url: str
    dataset_date: date | None
    source_payload: dict

    @property
    def source_label_de(self) -> str:
        if self.source_name == IMMO_TELEKOM_SOURCE_NAME:
            return "ImmoScout24 / Telekom"
        if self.source_name == BBA_SOURCE_NAME:
            return BBA_ATTRIBUTION
        return self.source_name

    @property
    def precision_label_de(self) -> str:
        return {
            "listing_specific_provider": "anzeigenspezifische Provider-Angabe",
            "grid_100m": "100×100-m-Raster",
        }.get(self.evidence_precision, self.evidence_precision)


@dataclass(frozen=True, slots=True)
class InternetAssessment:
    property_id: int
    evidence: tuple[InternetEvidenceView, ...]
    max_defensible_download_mbps: int | None
    minimum_download_mbps: int | None
    status: str
    starlink_fallback: bool

    @property
    def status_label_de(self) -> str:
        return {
            "sufficient": "Anforderung erfüllt",
            "insufficient": "unter Mindestanforderung",
            "unknown": "nicht belastbar bestimmbar",
            "available": "Festnetz belegt",
        }[self.status]


@dataclass(frozen=True, slots=True)
class BroadbandDatasetInfo:
    table_name: str
    feature_count: int
    artifact_sha256: str


def parse_immoscout_telekom_internet(
    body: str,
    *,
    expected_scout_id: str | None = None,
) -> ImmoScoutTelekomInternet | None:
    scout_match = _SCOUT_ID_RE.search(body)
    if scout_match is None:
        return None
    scout_id = scout_match.group("id")
    if expected_scout_id is not None and scout_id != expected_scout_id:
        return None

    available_match = _AVAILABILITY_RE.search(body)
    speed_match = _SPEED_RE.search(body)
    if available_match is None and speed_match is None:
        return None

    availability = (
        available_match.group(1).casefold() == "true"
        if available_match is not None
        else None
    )
    speed = int(speed_match.group("speed")) if speed_match is not None else None
    provider_match = _PROVIDER_URL_RE.search(body)

    if availability is True:
        state = "available"
    elif availability is False:
        state = "unavailable"
        speed = None
    else:
        state = "unknown"

    return ImmoScoutTelekomInternet(
        scout_id=scout_id,
        availability_state=state,
        max_download_mbps=speed,
        provider_url=provider_match.group("url") if provider_match else None,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _bba_feature_table(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "select table_name from gpkg_contents where data_type='features'"
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("Breitbandatlas GeoPackage must contain exactly one feature layer")
    return str(rows[0][0])


def validate_breitbandatlas_gpkg(path: str | Path) -> BroadbandDatasetInfo:
    source_path = Path(path)
    connection = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    try:
        table = _bba_feature_table(connection)
        geometry = connection.execute(
            "select geometry_type_name,srs_id from gpkg_geometry_columns where table_name=?",
            (table,),
        ).fetchone()
        if geometry is None or str(geometry[0]).upper() != "POLYGON" or int(geometry[1]) != 25832:
            raise ValueError("Breitbandatlas layer must be POLYGON EPSG:25832")

        columns = {str(row[1]) for row in connection.execute(f'pragma table_info("{table}")')}
        required = {"id", "geom", "raster_id", "ags"}
        required.update(
            f"{BBA_HOUSEHOLD_PREFIX}alle_{speed}" for speed in BBA_SPEED_CLASSES
        )
        missing = sorted(required - columns)
        if missing:
            raise ValueError("Breitbandatlas GeoPackage missing columns: " + ", ".join(missing))

        rtree = f"rtree_{table}_geom"
        rtree_exists = connection.execute(
            "select 1 from sqlite_master where type='table' and name=?",
            (rtree,),
        ).fetchone()
        if rtree_exists is None:
            raise ValueError("Breitbandatlas GeoPackage has no geometry RTree index")

        feature_count = int(connection.execute(f'select count(*) from "{table}"').fetchone()[0])
        if feature_count <= 0:
            raise ValueError("Breitbandatlas GeoPackage contains no grid cells")
    finally:
        connection.close()

    return BroadbandDatasetInfo(
        table_name=table,
        feature_count=feature_count,
        artifact_sha256=_sha256_file(source_path),
    )


def publish_breitbandatlas_dataset(
    session: Session,
    path: str | Path,
    *,
    dataset_date: date = BBA_DATASET_DATE,
) -> BroadbandDatasetInfo:
    info = validate_breitbandatlas_gpkg(path)
    statement = pg_insert(InternetDatasetState).values(
        source_name=BBA_SOURCE_NAME,
        country_code=BBA_COUNTRY_CODE,
        dataset_date=dataset_date,
        coverage_status="ok",
        source_url=BBA_SOURCE_URL,
        attribution=BBA_ATTRIBUTION,
        evidence_precision="grid_100m",
        artifact_path=str(Path(path)),
        artifact_sha256=info.artifact_sha256,
        feature_count=info.feature_count,
    )
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[InternetDatasetState.source_name],
            set_={
                "country_code": BBA_COUNTRY_CODE,
                "dataset_date": dataset_date,
                "coverage_status": "ok",
                "source_url": BBA_SOURCE_URL,
                "attribution": BBA_ATTRIBUTION,
                "evidence_precision": "grid_100m",
                "artifact_path": str(Path(path)),
                "artifact_sha256": info.artifact_sha256,
                "feature_count": info.feature_count,
                "imported_at": func.now(),
            },
        )
    )
    session.commit()
    return info


def _decimal_percent(value: object | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.001"))


def lookup_breitbandatlas_grid(
    path: str | Path,
    *,
    longitude: float,
    latitude: float,
) -> BroadbandGridCell | None:
    east, north = Transformer.from_crs(4326, 25832, always_xy=True).transform(
        longitude,
        latitude,
    )
    connection = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        table = _bba_feature_table(connection)
        rtree = f"rtree_{table}_geom"
        column_names = ["raster_id", "ags"] + [
            f"{BBA_HOUSEHOLD_PREFIX}{technology}_{speed}"
            for technology in BBA_TECHNOLOGIES
            for speed in BBA_SPEED_CLASSES
        ]
        quoted_columns = ",".join(f't."{name}"' for name in column_names)
        row = connection.execute(
            (
                f'SELECT {quoted_columns} '
                f'FROM "{table}" t JOIN "{rtree}" r ON r.id=t.id '
                "WHERE r.minx <= ? AND r.maxx >= ? AND r.miny <= ? AND r.maxy >= ? "
                "LIMIT 1"
            ),
            (east, east, north, north),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None

    values = dict(zip(column_names, row, strict=True))
    coverage_by_technology = {
        technology: {
            speed: _decimal_percent(
                values[f"{BBA_HOUSEHOLD_PREFIX}{technology}_{speed}"]
            )
            for speed in BBA_SPEED_CLASSES
        }
        for technology in BBA_TECHNOLOGIES
    }
    return BroadbandGridCell(
        raster_id=str(values["raster_id"]),
        ags=str(values["ags"]) if values["ags"] is not None else None,
        coverage_all=coverage_by_technology["alle"],
        coverage_by_technology=coverage_by_technology,
    )


def _upsert_evidence(session: Session, values: dict[str, object]) -> None:
    statement = pg_insert(PropertyInternetEvidence).values(**values)
    update_columns = [
        "country_code",
        "evidence_kind",
        "evidence_precision",
        "provider_name",
        "availability_state",
        "max_download_mbps",
        "technology",
        "coverage_percent",
        "monthly_price_eur",
        "source_url",
        "dataset_date",
        "observed_at",
        "source_payload",
    ]
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[
                PropertyInternetEvidence.property_id,
                PropertyInternetEvidence.source_name,
                PropertyInternetEvidence.source_reference,
            ],
            set_={name: getattr(statement.excluded, name) for name in update_columns},
        )
    )


def store_immoscout_telekom_evidence(
    session: Session,
    listing: PropertyListing,
    evidence: ImmoScoutTelekomInternet,
    *,
    observed_at: datetime | None = None,
) -> None:
    _upsert_evidence(
        session,
        {
            "property_id": listing.property_id,
            "country_code": "DE",
            "source_name": IMMO_TELEKOM_SOURCE_NAME,
            "source_reference": evidence.scout_id,
            "evidence_kind": "fixed_provider_listing",
            "evidence_precision": "listing_specific_provider",
            "provider_name": IMMO_PROVIDER_NAME,
            "availability_state": evidence.availability_state,
            "max_download_mbps": evidence.max_download_mbps,
            "technology": None,
            "coverage_percent": None,
            "monthly_price_eur": None,
            "source_url": listing.url,
            "dataset_date": None,
            "observed_at": observed_at or datetime.now(UTC),
            "source_payload": {
                "provider_url": evidence.provider_url,
                "price_semantics": "unknown",
            },
        },
    )


def _grid_payload(cell: BroadbandGridCell) -> dict:
    return {
        "raster_id": cell.raster_id,
        "ags": cell.ags,
        "raster_size_m": BBA_RASTER_SIZE_M,
        "coverage_all": {
            str(speed): (str(value) if value is not None else None)
            for speed, value in cell.coverage_all.items()
        },
        "coverage_by_technology": {
            technology: {
                str(speed): (str(value) if value is not None else None)
                for speed, value in values.items()
            }
            for technology, values in cell.coverage_by_technology.items()
        },
        "price_semantics": "unknown",
    }


def store_breitbandatlas_evidence(
    session: Session,
    property_row: Property,
    cell: BroadbandGridCell,
    *,
    observed_at: datetime | None = None,
) -> None:
    maximum = cell.max_defensible_download_mbps
    _upsert_evidence(
        session,
        {
            "property_id": property_row.id,
            "country_code": "DE",
            "source_name": BBA_SOURCE_NAME,
            "source_reference": cell.raster_id,
            "evidence_kind": "fixed_market_grid",
            "evidence_precision": "grid_100m",
            "provider_name": None,
            "availability_state": "available" if maximum is not None else "unknown",
            "max_download_mbps": maximum,
            "technology": "all",
            "coverage_percent": (
                cell.coverage_all.get(maximum) if maximum is not None else None
            ),
            "monthly_price_eur": None,
            "source_url": BBA_SOURCE_URL,
            "dataset_date": BBA_DATASET_DATE,
            "observed_at": observed_at or datetime.now(UTC),
            "source_payload": _grid_payload(cell),
        },
    )
    session.execute(
        delete(PropertyInternetEvidence).where(
            PropertyInternetEvidence.property_id == property_row.id,
            PropertyInternetEvidence.source_name == BBA_SOURCE_NAME,
            PropertyInternetEvidence.source_reference != cell.raster_id,
        )
    )


def broadband_dataset_path(session: Session) -> Path | None:
    row = session.get(InternetDatasetState, BBA_SOURCE_NAME)
    if (
        row is None
        or row.country_code != "DE"
        or row.coverage_status != "ok"
        or row.dataset_date != BBA_DATASET_DATE
        or not row.artifact_path
    ):
        return None
    path = Path(row.artifact_path)
    return path if path.is_file() else None


def property_grid_eligible(property_row: Property) -> bool:
    return bool(
        property_row.location is not None
        and property_row.location_precision in INTERNET_GRID_ELIGIBLE_LOCATION_PRECISIONS
    )


def assess_internet_evidence(
    property_id: int,
    evidence: tuple[InternetEvidenceView, ...],
    *,
    minimum_download_mbps: int | None = None,
) -> InternetAssessment:
    known_speeds = [
        item.max_download_mbps
        for item in evidence
        if item.availability_state == "available"
        and item.max_download_mbps is not None
    ]
    maximum = max(known_speeds) if known_speeds else None
    if minimum_download_mbps is not None:
        if maximum is None:
            status = "unknown"
        elif maximum >= minimum_download_mbps:
            status = "sufficient"
        else:
            status = "insufficient"
    else:
        status = "available" if maximum is not None else "unknown"

    return InternetAssessment(
        property_id=property_id,
        evidence=evidence,
        max_defensible_download_mbps=maximum,
        minimum_download_mbps=minimum_download_mbps,
        status=status,
        starlink_fallback=(
            maximum is None
            or (
                minimum_download_mbps is not None
                and maximum < minimum_download_mbps
            )
        ),
    )


def load_internet_assessments(
    session: Session,
    property_ids: set[int],
    *,
    minimum_download_mbps: int | None = None,
    country_code: str = "DE",
) -> dict[int, InternetAssessment]:
    if country_code != "DE" or not property_ids:
        return {}

    rows = session.scalars(
        select(PropertyInternetEvidence)
        .where(
            PropertyInternetEvidence.property_id.in_(property_ids),
            PropertyInternetEvidence.country_code == "DE",
        )
        .order_by(
            PropertyInternetEvidence.property_id,
            PropertyInternetEvidence.max_download_mbps.desc().nullslast(),
            PropertyInternetEvidence.id,
        )
    )
    grouped: dict[int, list[InternetEvidenceView]] = {property_id: [] for property_id in property_ids}
    for row in rows:
        grouped[row.property_id].append(
            InternetEvidenceView(
                source_name=row.source_name,
                source_reference=row.source_reference,
                evidence_kind=row.evidence_kind,
                evidence_precision=row.evidence_precision,
                provider_name=row.provider_name,
                availability_state=row.availability_state,
                max_download_mbps=row.max_download_mbps,
                technology=row.technology,
                coverage_percent=row.coverage_percent,
                monthly_price_eur=row.monthly_price_eur,
                source_url=row.source_url,
                dataset_date=row.dataset_date,
                source_payload=row.source_payload or {},
            )
        )

    return {
        property_id: assess_internet_evidence(
            property_id,
            tuple(evidence),
            minimum_download_mbps=minimum_download_mbps,
        )
        for property_id, evidence in grouped.items()
    }


async def fetch_immoscout_telekom_evidence(
    url: str,
    *,
    expected_scout_id: str,
) -> ImmoScoutTelekomInternet | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
    }
    async with httpx.AsyncClient(
        headers=headers,
        timeout=IMMO_DETAIL_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
    return parse_immoscout_telekom_internet(
        response.text,
        expected_scout_id=expected_scout_id,
    )


def active_immoscout_listings_for_internet(
    session: Session,
    *,
    limit: int,
) -> list[PropertyListing]:
    source = session.scalar(select(Source).where(Source.name == IMMO_SOURCE_NAME))
    if source is None:
        return []
    latest_observation = (
        select(func.max(PropertyInternetEvidence.observed_at))
        .where(
            PropertyInternetEvidence.property_id == PropertyListing.property_id,
            PropertyInternetEvidence.source_name == IMMO_TELEKOM_SOURCE_NAME,
            PropertyInternetEvidence.source_reference == PropertyListing.source_listing_id,
        )
        .correlate(PropertyListing)
        .scalar_subquery()
    )
    cutoff_dt = datetime.now(UTC) - timedelta(hours=IMMO_DETAIL_RECHECK_HOURS)
    return list(
        session.scalars(
            select(PropertyListing)
            .where(
                PropertyListing.source_id == source.id,
                PropertyListing.status == ListingStatus.ACTIVE,
                (latest_observation.is_(None)) | (latest_observation < cutoff_dt),
            )
            .order_by(
                latest_observation.asc().nullsfirst(),
                PropertyListing.last_seen_at.desc(),
                PropertyListing.id.desc(),
            )
            .limit(max(1, limit))
        )
    )
