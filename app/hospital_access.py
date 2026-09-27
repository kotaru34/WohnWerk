from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import BinaryIO
from xml.etree import ElementTree
from zipfile import ZipFile

from geoalchemy2 import Geography
from geoalchemy2.elements import WKTElement
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    and_,
    false,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base
from app.models import Property

BKA_SOURCE = "bundes-klinik-atlas"
BKA_OPEN_DATA_URL = "https://bundes-klinik-atlas.de/open-data/"
BKA_RECORD_URL = "https://bundes-klinik-atlas.de/krankenhaussuche/krankenhaus/{source_facility_id}/"
_SNAPSHOT_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})_TVERZ_Export\.xml$")


class HospitalFacility(Base):
    """One source-backed German hospital site from Bundes-Klinik-Atlas Open Data."""

    __tablename__ = "hospital_facilities"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_facility_id",
            name="uq_hospital_facilities_source_facility",
        ),
        Index("ix_hospital_facilities_country", "country_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default=BKA_SOURCE)
    source_facility_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="DE")
    region_code: Mapped[str | None] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    street: Mapped[str | None] = mapped_column(String(500))
    postal_code: Mapped[str | None] = mapped_column(String(5), index=True)
    city: Mapped[str | None] = mapped_column(String(160), index=True)
    website_url: Mapped[str | None] = mapped_column(String(1200))
    operator_type: Mapped[str | None] = mapped_column(String(120))
    children_hospital: Mapped[bool | None] = mapped_column(Boolean)
    security_mandate: Mapped[bool | None] = mapped_column(Boolean)
    location: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True)
    )

    # Values are preserved exactly enough to audit the source semantics. A current
    # emergency level is only considered confirmed when level is 1..3 and
    # emergency_level_unagreed is false.
    emergency_level: Mapped[int | None] = mapped_column(Integer)
    emergency_level_unagreed: Mapped[bool | None] = mapped_column(Boolean)
    severe_trauma: Mapped[bool | None] = mapped_column(Boolean)
    pediatric_emergency_level: Mapped[int | None] = mapped_column(Integer)
    special_emergency: Mapped[bool | None] = mapped_column(Boolean)
    stroke_unit: Mapped[bool | None] = mapped_column(Boolean)
    chest_pain_unit: Mapped[bool | None] = mapped_column(Boolean)

    source_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


@dataclass(frozen=True, slots=True)
class HospitalRecord:
    source_facility_id: str
    source_snapshot_date: date
    region_code: str
    name: str
    street: str
    postal_code: str
    city: str
    website_url: str | None
    operator_type: str | None
    children_hospital: bool
    security_mandate: bool
    longitude: float
    latitude: float
    emergency_level: int | None
    emergency_level_unagreed: bool | None
    severe_trauma: bool | None
    pediatric_emergency_level: int | None
    special_emergency: bool | None
    stroke_unit: bool | None
    chest_pain_unit: bool | None
    source_payload: dict


@dataclass(frozen=True, slots=True)
class HospitalAccess:
    property_id: int
    facility_id: int
    source_facility_id: str
    name: str
    city: str | None
    operator_type: str | None
    website_url: str | None
    air_distance_km: float
    emergency_level: int | None
    emergency_level_unagreed: bool | None
    severe_trauma: bool | None
    pediatric_emergency_level: int | None
    special_emergency: bool | None
    stroke_unit: bool | None
    chest_pain_unit: bool | None

    @property
    def source_url(self) -> str:
        return BKA_RECORD_URL.format(source_facility_id=self.source_facility_id)

    @property
    def confirmed_emergency_level(self) -> int | None:
        if self.emergency_level_unagreed:
            return None
        if self.emergency_level in {1, 2, 3}:
            return self.emergency_level
        return None

    @property
    def emergency_level_label(self) -> str:
        if self.emergency_level_unagreed:
            return "Notfallstufe noch nicht vereinbart"
        return {
            1: "Stufe 1 · Basisnotfallversorgung",
            2: "Stufe 2 · Erweiterte Notfallversorgung",
            3: "Stufe 3 · Umfassende Notfallversorgung",
        }.get(self.confirmed_emergency_level, "Keine bestätigte Notfallstufe")

    @property
    def capability_labels(self) -> tuple[str, ...]:
        labels: list[str] = []
        if self.confirmed_emergency_level is not None:
            labels.append(self.emergency_level_label)
        if self.severe_trauma:
            labels.append("Schwerverletztenversorgung")
        if self.pediatric_emergency_level in {1, 2, 3}:
            labels.append(f"Kinder-Notfallversorgung Stufe {self.pediatric_emergency_level}")
        if self.special_emergency:
            labels.append("Spezialversorgung")
        if self.stroke_unit:
            labels.append("Stroke Unit")
        if self.chest_pain_unit:
            labels.append("Chest Pain Unit")
        return tuple(labels)


@dataclass(frozen=True, slots=True)
class HospitalAccessSummary:
    nearest_hospital: HospitalAccess | None = None
    nearest_emergency: HospitalAccess | None = None
    nearest_advanced: HospitalAccess | None = None


@dataclass(frozen=True, slots=True)
class HospitalImportResult:
    snapshot_date: date
    imported: int
    removed: int


def _required(attrs: dict[str, str], key: str) -> str:
    value = attrs.get(key)
    if value is None:
        raise ValueError(f"Bundes-Klinik-Atlas field {key} is missing")
    return value


def _source_bool(value: str, field: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"1", "true"}:
        return True
    if normalized in {"0", "false"}:
        return False
    raise ValueError(f"Bundes-Klinik-Atlas field {field} has invalid boolean {value!r}")


def _source_int(value: str | None, field: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(
            f"Bundes-Klinik-Atlas field {field} has invalid integer {value!r}"
        ) from exc


def _source_float(value: str, field: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(
            f"Bundes-Klinik-Atlas field {field} has invalid coordinate {value!r}"
        ) from exc
    return result


def parse_bka_export(
    stream: BinaryIO,
    *,
    snapshot_date: date,
) -> list[HospitalRecord]:
    records: list[HospitalRecord] = []
    seen: set[str] = set()

    for _event, element in ElementTree.iterparse(stream, events=("end",)):
        if element.tag != "Standort":
            continue

        contact = element.find("StandortKontaktDaten")
        if contact is None:
            element.clear()
            continue
        contact_attrs = dict(contact.attrib)
        source_facility_id = _required(contact_attrs, "STOID")
        if source_facility_id in seen:
            raise ValueError(
                f"Bundes-Klinik-Atlas contains duplicate STOID {source_facility_id}"
            )
        seen.add(source_facility_id)

        longitude = _source_float(_required(contact_attrs, "Laengengrad"), "Laengengrad")
        latitude = _source_float(_required(contact_attrs, "Breitengrad"), "Breitengrad")
        if not -180.0 <= longitude <= 180.0 or not -90.0 <= latitude <= 90.0:
            raise ValueError(
                f"Bundes-Klinik-Atlas STOID {source_facility_id} has invalid coordinates"
            )

        emergency = element.find("StandortNotfallversorgung")
        emergency_attrs = dict(emergency.attrib) if emergency is not None else {}
        if emergency is None:
            emergency_level = None
            emergency_level_unagreed = None
            severe_trauma = None
            pediatric_emergency_level = None
            special_emergency = None
            stroke_unit = None
            chest_pain_unit = None
        else:
            emergency_level = _source_int(emergency_attrs.get("Stufe"), "Stufe")
            emergency_level_unagreed = _source_bool(
                _required(emergency_attrs, "StufeNichtVereinbart"),
                "StufeNichtVereinbart",
            )
            severe_trauma = _source_bool(
                _required(emergency_attrs, "Schwerverletztenversorgung"),
                "Schwerverletztenversorgung",
            )
            pediatric_emergency_level = _source_int(
                emergency_attrs.get("Kinder"),
                "Kinder",
            )
            special_emergency = _source_bool(
                _required(emergency_attrs, "Spezialversorgung"),
                "Spezialversorgung",
            )
            stroke_unit = _source_bool(
                _required(emergency_attrs, "StrokeUnit"),
                "StrokeUnit",
            )
            chest_pain_unit = _source_bool(
                _required(emergency_attrs, "ChestPainUnit"),
                "ChestPainUnit",
            )

        records.append(
            HospitalRecord(
                source_facility_id=source_facility_id,
                source_snapshot_date=snapshot_date,
                region_code=_required(contact_attrs, "Land"),
                name=_required(contact_attrs, "Name"),
                street=_required(contact_attrs, "Strasse"),
                postal_code=_required(contact_attrs, "PLZ"),
                city=_required(contact_attrs, "Ort"),
                website_url=contact_attrs.get("URL") or None,
                operator_type=contact_attrs.get("TraegerArt") or None,
                children_hospital=_source_bool(
                    _required(contact_attrs, "Kinderklinik"),
                    "Kinderklinik",
                ),
                security_mandate=_source_bool(
                    _required(contact_attrs, "Sicherstellungsauftrag"),
                    "Sicherstellungsauftrag",
                ),
                longitude=longitude,
                latitude=latitude,
                emergency_level=emergency_level,
                emergency_level_unagreed=emergency_level_unagreed,
                severe_trauma=severe_trauma,
                pediatric_emergency_level=pediatric_emergency_level,
                special_emergency=special_emergency,
                stroke_unit=stroke_unit,
                chest_pain_unit=chest_pain_unit,
                source_payload={
                    "contact": contact_attrs,
                    "emergency": emergency_attrs or None,
                },
            )
        )
        element.clear()

    return records


def parse_bka_archive(path: str | Path) -> tuple[date, list[HospitalRecord]]:
    archive_path = Path(path)
    with ZipFile(archive_path) as archive:
        members = [
            name
            for name in archive.namelist()
            if name.endswith("_TVERZ_Export.xml") and not name.startswith("__MACOSX/")
        ]
        if len(members) != 1:
            raise ValueError(
                "Bundes-Klinik-Atlas archive must contain exactly one TVERZ export XML"
            )
        member = members[0]
        match = _SNAPSHOT_RE.search(member)
        if match is None:
            raise ValueError("Bundes-Klinik-Atlas export filename has no snapshot date")
        snapshot_date = date.fromisoformat(match.group("date"))
        with archive.open(member) as stream:
            records = parse_bka_export(stream, snapshot_date=snapshot_date)
    return snapshot_date, records


def import_bka_archive(session: Session, path: str | Path) -> HospitalImportResult:
    snapshot_date, records = parse_bka_archive(path)
    existing = {
        row.source_facility_id: row
        for row in session.scalars(
            select(HospitalFacility).where(HospitalFacility.source == BKA_SOURCE)
        )
    }
    seen: set[str] = set()

    for record in records:
        seen.add(record.source_facility_id)
        row = existing.get(record.source_facility_id)
        if row is None:
            row = HospitalFacility(
                source=BKA_SOURCE,
                source_facility_id=record.source_facility_id,
                source_snapshot_date=record.source_snapshot_date,
                country_code="DE",
                name=record.name,
            )
            session.add(row)

        row.source_snapshot_date = record.source_snapshot_date
        row.country_code = "DE"
        row.region_code = record.region_code
        row.name = record.name
        row.street = record.street
        row.postal_code = record.postal_code
        row.city = record.city
        row.website_url = record.website_url
        row.operator_type = record.operator_type
        row.children_hospital = record.children_hospital
        row.security_mandate = record.security_mandate
        row.location = WKTElement(
            f"POINT({record.longitude:.10f} {record.latitude:.10f})",
            srid=4326,
        )
        row.emergency_level = record.emergency_level
        row.emergency_level_unagreed = record.emergency_level_unagreed
        row.severe_trauma = record.severe_trauma
        row.pediatric_emergency_level = record.pediatric_emergency_level
        row.special_emergency = record.special_emergency
        row.stroke_unit = record.stroke_unit
        row.chest_pain_unit = record.chest_pain_unit
        row.source_payload = record.source_payload

    stale = [
        row
        for source_facility_id, row in existing.items()
        if source_facility_id not in seen
    ]
    for row in stale:
        session.delete(row)

    session.commit()
    return HospitalImportResult(
        snapshot_date=snapshot_date,
        imported=len(records),
        removed=len(stale),
    )


def _nearest_access_stmt(
    property_ids: set[int],
    *,
    min_emergency_level: int | None,
):
    distance_m = func.ST_Distance(Property.location, HospitalFacility.location)
    facility_conditions = [
        HospitalFacility.country_code == "DE",
        HospitalFacility.location.is_not(None),
    ]
    if min_emergency_level is not None:
        facility_conditions.extend(
            [
                HospitalFacility.emergency_level_unagreed.is_(False),
                HospitalFacility.emergency_level >= min_emergency_level,
                HospitalFacility.emergency_level <= 3,
            ]
        )

    candidates = (
        select(
            Property.id.label("property_id"),
            HospitalFacility.id.label("facility_id"),
            HospitalFacility.source_facility_id.label("source_facility_id"),
            HospitalFacility.name.label("name"),
            HospitalFacility.city.label("city"),
            HospitalFacility.operator_type.label("operator_type"),
            HospitalFacility.website_url.label("website_url"),
            HospitalFacility.emergency_level.label("emergency_level"),
            HospitalFacility.emergency_level_unagreed.label("emergency_level_unagreed"),
            HospitalFacility.severe_trauma.label("severe_trauma"),
            HospitalFacility.pediatric_emergency_level.label("pediatric_emergency_level"),
            HospitalFacility.special_emergency.label("special_emergency"),
            HospitalFacility.stroke_unit.label("stroke_unit"),
            HospitalFacility.chest_pain_unit.label("chest_pain_unit"),
            (distance_m / 1000.0).label("air_distance_km"),
            func.row_number()
            .over(
                partition_by=Property.id,
                order_by=(distance_m.asc(), HospitalFacility.id.asc()),
            )
            .label("nearest_rank"),
        )
        .select_from(Property)
        .join(HospitalFacility, and_(*facility_conditions))
        .where(
            Property.id.in_(property_ids),
            Property.location.is_not(None),
        )
        .subquery("nearest_hospital_candidates")
    )
    return select(candidates).where(candidates.c.nearest_rank == 1)


def _access_from_mapping(row) -> HospitalAccess:
    return HospitalAccess(
        property_id=int(row["property_id"]),
        facility_id=int(row["facility_id"]),
        source_facility_id=str(row["source_facility_id"]),
        name=str(row["name"]),
        city=row["city"],
        operator_type=row["operator_type"],
        website_url=row["website_url"],
        air_distance_km=float(row["air_distance_km"]),
        emergency_level=(
            int(row["emergency_level"]) if row["emergency_level"] is not None else None
        ),
        emergency_level_unagreed=row["emergency_level_unagreed"],
        severe_trauma=row["severe_trauma"],
        pediatric_emergency_level=(
            int(row["pediatric_emergency_level"])
            if row["pediatric_emergency_level"] is not None
            else None
        ),
        special_emergency=row["special_emergency"],
        stroke_unit=row["stroke_unit"],
        chest_pain_unit=row["chest_pain_unit"],
    )


def load_nearest_hospital_access(
    session: Session,
    property_ids: set[int],
    *,
    min_emergency_level: int | None = None,
) -> dict[int, HospitalAccess]:
    if not property_ids:
        return {}
    rows = session.execute(
        _nearest_access_stmt(
            property_ids,
            min_emergency_level=min_emergency_level,
        )
    ).mappings()
    return {
        access.property_id: access
        for access in (_access_from_mapping(row) for row in rows)
    }


def load_hospital_access_summaries(
    session: Session,
    property_ids: set[int],
) -> dict[int, HospitalAccessSummary]:
    if not property_ids:
        return {}

    nearest = load_nearest_hospital_access(session, property_ids)
    emergency = load_nearest_hospital_access(
        session,
        property_ids,
        min_emergency_level=1,
    )
    advanced = load_nearest_hospital_access(
        session,
        property_ids,
        min_emergency_level=2,
    )
    return {
        property_id: HospitalAccessSummary(
            nearest_hospital=nearest.get(property_id),
            nearest_emergency=emergency.get(property_id),
            nearest_advanced=advanced.get(property_id),
        )
        for property_id in property_ids
        if property_id in nearest or property_id in emergency or property_id in advanced
    }


def confirmed_emergency_distance_m_expr():
    distance_m = func.ST_Distance(Property.location, HospitalFacility.location)
    return (
        select(func.min(distance_m))
        .select_from(HospitalFacility)
        .where(
            HospitalFacility.country_code == "DE",
            HospitalFacility.location.is_not(None),
            HospitalFacility.emergency_level_unagreed.is_(False),
            HospitalFacility.emergency_level >= 1,
            HospitalFacility.emergency_level <= 3,
        )
        .correlate(Property)
        .scalar_subquery()
    )


def hospital_distance_rejection_condition(
    max_distance_km: Decimal | None,
    *,
    fail_closed: bool,
    country_code: str,
):
    if country_code != "DE" or max_distance_km is None:
        return false()

    distance_m = confirmed_emergency_distance_m_expr()
    threshold_m = float(max_distance_km) * 1000.0
    if fail_closed:
        return (distance_m.is_(None)) | (distance_m > threshold_m)
    return distance_m.is_not(None) & (distance_m > threshold_m)
