from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import BinaryIO
from zipfile import ZipFile

import httpx
from geoalchemy2 import Geography
from geoalchemy2.elements import WKTElement
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    and_,
    delete,
    func,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base
from app.models import Property

BKA_SOURCE_NAME = "bundes-klinik-atlas"
BKA_COUNTRY_CODE = "DE"
BKA_OPEN_DATA_URL = "https://bundes-klinik-atlas.de/open-data/"
BKA_EXPORT_URL = (
    "https://bundes-klinik-atlas.de/fileadmin/dataextracts/"
    "Bundes-Klinik-Atlas_Datenexport_20260901.zip"
)
BKA_DATASET_DATE = date(2026, 9, 1)
BKA_UPSERT_BATCH_SIZE = 500


class HospitalDatasetState(Base):
    """Completeness/provenance marker for an imported hospital snapshot."""

    __tablename__ = "hospital_dataset_states"

    source_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    dataset_date: Mapped[date] = mapped_column(Date, nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(20), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1200), nullable=False)
    facility_count: Mapped[int] = mapped_column(Integer, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class HospitalFacility(Base):
    """Source-backed hospital site and explicit emergency capability facts."""

    __tablename__ = "hospital_facilities"
    __table_args__ = (
        UniqueConstraint("source_name", "source_id", name="uq_hospital_facility_source_id"),
        Index("ix_hospital_facilities_country_source", "country_code", "source_name"),
        Index("ix_hospital_facilities_emergency", "country_code", "emergency_level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(
        ForeignKey("hospital_dataset_states.source_name", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(String(80), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    state_code: Mapped[str | None] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    street: Mapped[str | None] = mapped_column(String(500))
    postal_code: Mapped[str | None] = mapped_column(String(10), index=True)
    city: Mapped[str | None] = mapped_column(String(200), index=True)
    facility_url: Mapped[str | None] = mapped_column(String(1200))
    carrier_type: Mapped[str | None] = mapped_column(String(160))
    is_children_hospital: Mapped[bool | None] = mapped_column(Boolean)
    assurance_contract: Mapped[bool | None] = mapped_column(Boolean)
    location: Mapped[object | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True)
    )
    emergency_level: Mapped[int | None] = mapped_column(Integer)
    emergency_level_not_agreed: Mapped[bool | None] = mapped_column(Boolean)
    severe_injury_care: Mapped[bool | None] = mapped_column(Boolean)
    children_emergency_level: Mapped[int | None] = mapped_column(Integer)
    specialist_emergency_care: Mapped[bool | None] = mapped_column(Boolean)
    stroke_unit: Mapped[bool | None] = mapped_column(Boolean)
    chest_pain_unit: Mapped[bool | None] = mapped_column(Boolean)
    dataset_date: Mapped[date] = mapped_column(Date, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


@dataclass(frozen=True, slots=True)
class HospitalFacilityRecord:
    source_id: str
    state_code: str | None
    name: str
    street: str | None
    postal_code: str | None
    city: str | None
    facility_url: str | None
    carrier_type: str | None
    longitude: float
    latitude: float
    is_children_hospital: bool | None = None
    assurance_contract: bool | None = None
    emergency_level: int | None = None
    emergency_level_not_agreed: bool | None = None
    severe_injury_care: bool | None = None
    children_emergency_level: int | None = None
    specialist_emergency_care: bool | None = None
    stroke_unit: bool | None = None
    chest_pain_unit: bool | None = None

    @property
    def confirmed_emergency(self) -> bool:
        return (
            self.emergency_level in {1, 2, 3}
            and self.emergency_level_not_agreed is not True
        )


@dataclass(frozen=True, slots=True)
class HospitalAccess:
    property_id: int
    facility_id: int
    source_id: str
    name: str
    street: str | None
    postal_code: str | None
    city: str | None
    facility_url: str | None
    carrier_type: str | None
    is_children_hospital: bool | None
    air_distance_km: float
    emergency_level: int | None
    severe_injury_care: bool | None
    children_emergency_level: int | None
    specialist_emergency_care: bool | None
    stroke_unit: bool | None
    chest_pain_unit: bool | None

    @property
    def facility_type_label_de(self) -> str:
        return "Kinderklinik" if self.is_children_hospital else "Krankenhausstandort"

    @property
    def emergency_level_label_de(self) -> str | None:
        return {
            1: "Notfallstufe 1 · Basisnotfallversorgung",
            2: "Notfallstufe 2 · Erweiterte Notfallversorgung",
            3: "Notfallstufe 3 · Umfassende Notfallversorgung",
        }.get(self.emergency_level)

    @property
    def capability_labels_de(self) -> tuple[str, ...]:
        labels: list[str] = []
        if self.emergency_level_label_de is not None:
            labels.append(self.emergency_level_label_de)
        if self.severe_injury_care:
            labels.append("Schwerverletztenversorgung")
        if self.children_emergency_level in {1, 2, 3}:
            labels.append(f"Kinder-Notfallstufe {self.children_emergency_level}")
        if self.specialist_emergency_care:
            labels.append("Spezialversorgung")
        if self.stroke_unit:
            labels.append("Stroke Unit")
        if self.chest_pain_unit:
            labels.append("Chest Pain Unit")
        return tuple(labels)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


def _bool_attr(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    if value in {"1", "true", "True"}:
        return True
    if value in {"0", "false", "False"}:
        return False
    raise ValueError(f"invalid boolean attribute: {value!r}")


def _int_attr(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def parse_bundes_klinik_atlas_xml(stream: BinaryIO) -> list[HospitalFacilityRecord]:
    """Parse one complete TVERZ export without inventing missing capability facts."""

    records: list[HospitalFacilityRecord] = []
    for _event, element in ET.iterparse(stream, events=("end",)):
        if _local_name(element.tag) != "Standort":
            continue

        children = {_local_name(child.tag): child for child in list(element)}
        contact = children.get("StandortKontaktDaten")
        if contact is None:
            element.clear()
            continue

        source_id = _optional_text(contact.get("STOID"))
        name = _optional_text(contact.get("Name"))
        longitude_text = _optional_text(contact.get("Laengengrad"))
        latitude_text = _optional_text(contact.get("Breitengrad"))
        if not source_id or not name or not longitude_text or not latitude_text:
            element.clear()
            continue

        longitude = float(longitude_text)
        latitude = float(latitude_text)
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise ValueError(f"invalid coordinates for hospital site {source_id}")

        emergency = children.get("StandortNotfallversorgung")
        records.append(
            HospitalFacilityRecord(
                source_id=source_id,
                state_code=_optional_text(contact.get("Land")),
                name=name,
                street=_optional_text(contact.get("Strasse")),
                postal_code=_optional_text(contact.get("PLZ")),
                city=_optional_text(contact.get("Ort")),
                facility_url=_optional_text(contact.get("URL")),
                carrier_type=_optional_text(contact.get("TraegerArt")),
                longitude=longitude,
                latitude=latitude,
                is_children_hospital=_bool_attr(contact.get("Kinderklinik")),
                assurance_contract=_bool_attr(contact.get("Sicherstellungsauftrag")),
                emergency_level=(
                    _int_attr(emergency.get("Stufe")) if emergency is not None else None
                ),
                emergency_level_not_agreed=(
                    _bool_attr(emergency.get("StufeNichtVereinbart"))
                    if emergency is not None
                    else None
                ),
                severe_injury_care=(
                    _bool_attr(emergency.get("Schwerverletztenversorgung"))
                    if emergency is not None
                    else None
                ),
                children_emergency_level=(
                    _int_attr(emergency.get("Kinder")) if emergency is not None else None
                ),
                specialist_emergency_care=(
                    _bool_attr(emergency.get("Spezialversorgung"))
                    if emergency is not None
                    else None
                ),
                stroke_unit=(
                    _bool_attr(emergency.get("StrokeUnit")) if emergency is not None else None
                ),
                chest_pain_unit=(
                    _bool_attr(emergency.get("ChestPainUnit")) if emergency is not None else None
                ),
            )
        )
        element.clear()

    if not records:
        raise ValueError("Bundes-Klinik-Atlas export contains no usable hospital sites")
    if len({record.source_id for record in records}) != len(records):
        raise ValueError("Bundes-Klinik-Atlas export contains duplicate STOID values")
    return records


def parse_bundes_klinik_atlas_zip(payload: bytes) -> list[HospitalFacilityRecord]:
    with ZipFile(BytesIO(payload)) as archive:
        candidates = [
            name
            for name in archive.namelist()
            if name.endswith("_TVERZ_Export.xml") and not name.startswith("__MACOSX/")
        ]
        if len(candidates) != 1:
            raise ValueError("expected exactly one TVERZ export XML in Bundes-Klinik-Atlas ZIP")
        with archive.open(candidates[0]) as stream:
            return parse_bundes_klinik_atlas_xml(stream)


def download_bundes_klinik_atlas_zip(
    *,
    url: str = BKA_EXPORT_URL,
    timeout_seconds: float = 30.0,
) -> bytes:
    response = httpx.get(url, timeout=timeout_seconds, follow_redirects=True)
    response.raise_for_status()
    return response.content


def _facility_values(
    record: HospitalFacilityRecord,
    *,
    dataset_date: date,
) -> dict[str, object]:
    return {
        "source_name": BKA_SOURCE_NAME,
        "source_id": record.source_id,
        "country_code": BKA_COUNTRY_CODE,
        "state_code": record.state_code,
        "name": record.name,
        "street": record.street,
        "postal_code": record.postal_code,
        "city": record.city,
        "facility_url": record.facility_url,
        "carrier_type": record.carrier_type,
        "is_children_hospital": record.is_children_hospital,
        "assurance_contract": record.assurance_contract,
        "location": WKTElement(
            f"POINT({record.longitude:.12f} {record.latitude:.12f})", srid=4326
        ),
        "emergency_level": record.emergency_level,
        "emergency_level_not_agreed": record.emergency_level_not_agreed,
        "severe_injury_care": record.severe_injury_care,
        "children_emergency_level": record.children_emergency_level,
        "specialist_emergency_care": record.specialist_emergency_care,
        "stroke_unit": record.stroke_unit,
        "chest_pain_unit": record.chest_pain_unit,
        "dataset_date": dataset_date,
    }


def upsert_bundes_klinik_atlas_snapshot(
    session: Session,
    records: Iterable[HospitalFacilityRecord],
    *,
    dataset_date: date = BKA_DATASET_DATE,
    source_url: str = BKA_OPEN_DATA_URL,
) -> int:
    """Atomically replace the current DE snapshot after a complete successful parse."""

    rows = list(records)
    if not rows:
        raise ValueError("refusing to publish an empty hospital snapshot")
    source_ids = {record.source_id for record in rows}
    if len(source_ids) != len(rows):
        raise ValueError("refusing to publish a hospital snapshot with duplicate STOID values")

    state_insert = pg_insert(HospitalDatasetState).values(
        source_name=BKA_SOURCE_NAME,
        country_code=BKA_COUNTRY_CODE,
        dataset_date=dataset_date,
        coverage_status="importing",
        source_url=source_url,
        facility_count=0,
    )
    session.execute(
        state_insert.on_conflict_do_update(
            index_elements=[HospitalDatasetState.source_name],
            set_={
                "country_code": BKA_COUNTRY_CODE,
                "dataset_date": dataset_date,
                "coverage_status": "importing",
                "source_url": source_url,
                "facility_count": 0,
                "imported_at": func.now(),
            },
        )
    )

    values = [_facility_values(record, dataset_date=dataset_date) for record in rows]
    update_columns = [
        "country_code",
        "state_code",
        "name",
        "street",
        "postal_code",
        "city",
        "facility_url",
        "carrier_type",
        "is_children_hospital",
        "assurance_contract",
        "location",
        "emergency_level",
        "emergency_level_not_agreed",
        "severe_injury_care",
        "children_emergency_level",
        "specialist_emergency_care",
        "stroke_unit",
        "chest_pain_unit",
        "dataset_date",
    ]
    for start in range(0, len(values), BKA_UPSERT_BATCH_SIZE):
        statement = pg_insert(HospitalFacility).values(
            values[start : start + BKA_UPSERT_BATCH_SIZE]
        )
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[HospitalFacility.source_name, HospitalFacility.source_id],
                set_={name: getattr(statement.excluded, name) for name in update_columns},
            )
        )

    session.execute(
        delete(HospitalFacility).where(
            HospitalFacility.source_name == BKA_SOURCE_NAME,
            HospitalFacility.source_id.not_in(source_ids),
        )
    )

    state_ready = pg_insert(HospitalDatasetState).values(
        source_name=BKA_SOURCE_NAME,
        country_code=BKA_COUNTRY_CODE,
        dataset_date=dataset_date,
        coverage_status="ok",
        source_url=source_url,
        facility_count=len(rows),
    )
    session.execute(
        state_ready.on_conflict_do_update(
            index_elements=[HospitalDatasetState.source_name],
            set_={
                "country_code": BKA_COUNTRY_CODE,
                "dataset_date": dataset_date,
                "coverage_status": "ok",
                "source_url": source_url,
                "facility_count": len(rows),
                "imported_at": func.now(),
            },
        )
    )
    session.commit()
    return len(rows)


def hospital_dataset_ready(session: Session, *, country_code: str = "DE") -> bool:
    return bool(
        session.scalar(
            select(HospitalDatasetState.coverage_status).where(
                HospitalDatasetState.source_name == BKA_SOURCE_NAME,
                HospitalDatasetState.country_code == country_code,
            )
        )
        == "ok"
    )


def confirmed_emergency_facility_condition():
    return and_(
        HospitalFacility.source_name == BKA_SOURCE_NAME,
        HospitalFacility.country_code == BKA_COUNTRY_CODE,
        HospitalFacility.location.is_not(None),
        HospitalFacility.emergency_level.in_((1, 2, 3)),
        HospitalFacility.emergency_level_not_agreed.is_not(True),
    )


def _nearest_facility_stmt(property_ids: set[int], *, emergency_only: bool):
    distance_km = (
        func.ST_Distance(Property.location, HospitalFacility.location) / 1000.0
    ).label("air_distance_km")
    conditions = [
        Property.id.in_(property_ids),
        Property.location.is_not(None),
        HospitalFacility.source_name == BKA_SOURCE_NAME,
        HospitalFacility.country_code == BKA_COUNTRY_CODE,
        HospitalFacility.location.is_not(None),
    ]
    if emergency_only:
        conditions.append(confirmed_emergency_facility_condition())
    candidates = (
        select(
            Property.id.label("property_id"),
            HospitalFacility.id.label("facility_id"),
            HospitalFacility.source_id,
            HospitalFacility.name,
            HospitalFacility.street,
            HospitalFacility.postal_code,
            HospitalFacility.city,
            HospitalFacility.facility_url,
            HospitalFacility.carrier_type,
            HospitalFacility.is_children_hospital,
            HospitalFacility.emergency_level,
            HospitalFacility.severe_injury_care,
            HospitalFacility.children_emergency_level,
            HospitalFacility.specialist_emergency_care,
            HospitalFacility.stroke_unit,
            HospitalFacility.chest_pain_unit,
            distance_km,
            func.row_number()
            .over(
                partition_by=Property.id,
                order_by=(distance_km.asc(), HospitalFacility.id.asc()),
            )
            .label("nearest_rank"),
        )
        .select_from(Property)
        .join(HospitalFacility, true())
        .where(*conditions)
        .subquery(
            "nearest_confirmed_emergency_candidates"
            if emergency_only
            else "nearest_hospital_candidates"
        )
    )
    return select(candidates).where(candidates.c.nearest_rank == 1)


def nearest_hospital_stmt(property_ids: set[int]):
    return _nearest_facility_stmt(property_ids, emergency_only=False)


def nearest_confirmed_emergency_stmt(property_ids: set[int]):
    return _nearest_facility_stmt(property_ids, emergency_only=True)


def _access_from_rows(rows) -> dict[int, HospitalAccess]:
    return {
        int(row["property_id"]): HospitalAccess(
            property_id=int(row["property_id"]),
            facility_id=int(row["facility_id"]),
            source_id=str(row["source_id"]),
            name=str(row["name"]),
            street=row["street"],
            postal_code=row["postal_code"],
            city=row["city"],
            facility_url=row["facility_url"],
            carrier_type=row["carrier_type"],
            is_children_hospital=row["is_children_hospital"],
            air_distance_km=float(row["air_distance_km"]),
            emergency_level=(
                int(row["emergency_level"]) if row["emergency_level"] in {1, 2, 3} else None
            ),
            severe_injury_care=row["severe_injury_care"],
            children_emergency_level=row["children_emergency_level"],
            specialist_emergency_care=row["specialist_emergency_care"],
            stroke_unit=row["stroke_unit"],
            chest_pain_unit=row["chest_pain_unit"],
        )
        for row in rows
        if row["air_distance_km"] is not None
    }


def load_nearest_hospital_access(
    session: Session,
    property_ids: set[int],
    *,
    country_code: str = "DE",
) -> dict[int, HospitalAccess]:
    if country_code != BKA_COUNTRY_CODE or not property_ids:
        return {}
    if not hospital_dataset_ready(session, country_code=country_code):
        return {}
    return _access_from_rows(session.execute(nearest_hospital_stmt(property_ids)).mappings())


def load_confirmed_emergency_access(
    session: Session,
    property_ids: set[int],
    *,
    country_code: str = "DE",
) -> dict[int, HospitalAccess]:
    if country_code != BKA_COUNTRY_CODE or not property_ids:
        return {}
    if not hospital_dataset_ready(session, country_code=country_code):
        return {}

    rows = session.execute(nearest_confirmed_emergency_stmt(property_ids)).mappings()
    return _access_from_rows(rows)


def hospital_distance_rejection_condition(
    max_distance_km: Decimal | None,
    *,
    fail_closed: bool = False,
):
    if max_distance_km is None:
        return None
    if max_distance_km <= 0:
        raise ValueError("hospital distance limit must be greater than zero")

    dataset_ready = (
        select(HospitalDatasetState.source_name)
        .where(
            HospitalDatasetState.source_name == BKA_SOURCE_NAME,
            HospitalDatasetState.country_code == BKA_COUNTRY_CODE,
            HospitalDatasetState.coverage_status == "ok",
        )
        .exists()
    )
    within_limit = (
        select(HospitalFacility.id)
        .where(
            confirmed_emergency_facility_condition(),
            func.ST_DWithin(
                Property.location,
                HospitalFacility.location,
                float(max_distance_km) * 1000.0,
            ),
        )
        .exists()
    )
    unknown = (~dataset_ready) | Property.location.is_(None)
    if fail_closed:
        return unknown | ~within_limit
    return dataset_ready & Property.location.is_not(None) & ~within_limit
