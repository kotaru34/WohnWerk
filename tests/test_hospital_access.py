from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.hospital_access import (
    HospitalAccess,
    hospital_distance_rejection_condition,
    parse_bka_archive,
    parse_bka_export,
)
from app.models import Property


def _sample_xml(*, unagreed: str = "0", level: str = "2") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Standorte>
  <Standort>
    <StandortKontaktDaten
      STOID="771003"
      Land="MV"
      Name="Klinikum Südstadt Rostock"
      Strasse="Südring 81"
      PLZ="18059"
      Ort="Rostock"
      URL="http://www.kliniksued-rostock.de"
      Telefon="+49 381 4401-0"
      EMail="info@example.invalid"
      TraegerArt="öffentlich"
      Kinderklinik="1"
      Sicherstellungsauftrag="0"
      GeoreferenzZone="33U"
      GeoreferenzOst="310754"
      GeoreferenzNord="5995361"
      Laengengrad="12.107577323914"
      Breitengrad="54.071629513465"
    />
    <StandortNotfallversorgung
      Stufe="{level}"
      Schwerverletztenversorgung="1"
      Kinder="1"
      Spezialversorgung="0"
      StrokeUnit="1"
      ChestPainUnit="0"
      StufeNichtVereinbart="{unagreed}"
    />
  </Standort>
</Standorte>
""".encode()


def test_bka_parser_preserves_official_identity_coordinates_and_capability() -> None:
    records = parse_bka_export(
        BytesIO(_sample_xml()),
        snapshot_date=date(2026, 9, 1),
    )

    assert len(records) == 1
    row = records[0]
    assert row.source_facility_id == "771003"
    assert row.source_snapshot_date == date(2026, 9, 1)
    assert row.region_code == "MV"
    assert row.name == "Klinikum Südstadt Rostock"
    assert row.postal_code == "18059"
    assert row.city == "Rostock"
    assert row.longitude == 12.107577323914
    assert row.latitude == 54.071629513465
    assert row.emergency_level == 2
    assert row.emergency_level_unagreed is False
    assert row.severe_trauma is True
    assert row.pediatric_emergency_level == 1
    assert row.stroke_unit is True
    assert row.chest_pain_unit is False
    assert row.source_payload["emergency"]["Stufe"] == "2"


def test_bka_archive_snapshot_date_comes_from_export_filename(tmp_path) -> None:
    archive_path = tmp_path / "Bundes-Klinik-Atlas_Datenexport_20260901.zip"
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "Bundes-Klinik-Atlas_Datenexport_20260901/2026-09-01_TVERZ_Export.xml",
            _sample_xml(),
        )
        archive.writestr(
            "Bundes-Klinik-Atlas_Datenexport_20260901/schema.xsd",
            "<schema />",
        )

    snapshot_date, records = parse_bka_archive(archive_path)

    assert snapshot_date == date(2026, 9, 1)
    assert [record.source_facility_id for record in records] == ["771003"]


def test_unagreed_emergency_level_is_not_presented_as_confirmed_capability() -> None:
    access = HospitalAccess(
        property_id=1,
        facility_id=2,
        source_facility_id="771003",
        name="Klinik",
        city="Rostock",
        operator_type="öffentlich",
        website_url=None,
        air_distance_km=12.5,
        emergency_level=3,
        emergency_level_unagreed=True,
        severe_trauma=False,
        pediatric_emergency_level=0,
        special_emergency=False,
        stroke_unit=False,
        chest_pain_unit=False,
    )

    assert access.confirmed_emergency_level is None
    assert access.emergency_level_label == "Notfallstufe noch nicht vereinbart"
    assert all("Stufe 3" not in label for label in access.capability_labels)


def test_confirmed_capabilities_are_source_backed_and_separate() -> None:
    access = HospitalAccess(
        property_id=1,
        facility_id=2,
        source_facility_id="771003",
        name="Klinik",
        city="Rostock",
        operator_type="öffentlich",
        website_url=None,
        air_distance_km=12.5,
        emergency_level=2,
        emergency_level_unagreed=False,
        severe_trauma=True,
        pediatric_emergency_level=1,
        special_emergency=False,
        stroke_unit=True,
        chest_pain_unit=True,
    )

    assert access.confirmed_emergency_level == 2
    assert access.capability_labels == (
        "Stufe 2 · Erweiterte Notfallversorgung",
        "Schwerverletztenversorgung",
        "Kinder-Notfallversorgung Stufe 1",
        "Stroke Unit",
        "Chest Pain Unit",
    )
    assert access.source_url.endswith("/krankenhaus/771003/")


def test_hospital_distance_rule_uses_only_confirmed_emergency_level_in_de() -> None:
    condition = hospital_distance_rejection_condition(
        Decimal("30"),
        fail_closed=False,
        country_code="DE",
    )
    compiled = select(Property.id).where(condition).compile(
        dialect=postgresql.dialect()
    )
    sql = str(compiled)

    assert "hospital_facilities" in sql
    assert "ST_Distance" in sql
    assert "emergency_level_unagreed IS false" in sql
    assert "emergency_level >=" in sql
    assert "emergency_level <=" in sql


def test_hospital_distance_rule_is_not_applied_to_austria() -> None:
    condition = hospital_distance_rejection_condition(
        Decimal("30"),
        fail_closed=True,
        country_code="AT",
    )
    compiled = select(Property.id).where(condition).compile(
        dialect=postgresql.dialect()
    )

    assert "hospital_facilities" not in str(compiled)
