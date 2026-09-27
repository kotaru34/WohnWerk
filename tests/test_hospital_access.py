from io import BytesIO

from sqlalchemy.dialects import postgresql

from app.hospital_access import (
    HospitalAccess,
    nearest_confirmed_emergency_stmt,
    nearest_hospital_stmt,
    parse_bundes_klinik_atlas_xml,
)

SAMPLE_XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<Standorte>
  <Standort>
    <StandortKontaktDaten STOID="771003" Land="MV" Name="Klinikum Suedstadt Rostock" Strasse="Suedring 81" PLZ="18059" Ort="Rostock" URL="https://example.test" Telefon="" EMail="" TraegerArt="oeffentlich" Kinderklinik="1" Sicherstellungsauftrag="0" GeoreferenzZone="33U" GeoreferenzOst="310754" GeoreferenzNord="5995361" Laengengrad="12.107577323914" Breitengrad="54.071629513465"/>
    <StandortNotfallversorgung Stufe="2" Schwerverletztenversorgung="1" Kinder="1" Spezialversorgung="0" StrokeUnit="1" ChestPainUnit="0" StufeNichtVereinbart="0"/>
  </Standort>
  <Standort>
    <StandortKontaktDaten STOID="999999" Land="BE" Name="Beispielklinik" Strasse="Test 1" PLZ="10115" Ort="Berlin" URL="" Telefon="" EMail="" TraegerArt="freigemeinnuetzig" Kinderklinik="0" Sicherstellungsauftrag="0" GeoreferenzZone="33U" GeoreferenzOst="0" GeoreferenzNord="0" Laengengrad="13.384" Breitengrad="52.532"/>
    <StandortNotfallversorgung Stufe="3" Schwerverletztenversorgung="0" Kinder="0" Spezialversorgung="1" StrokeUnit="0" ChestPainUnit="1" StufeNichtVereinbart="1"/>
  </Standort>
</Standorte>
'''


def test_bundes_klinik_atlas_parser_preserves_explicit_capability() -> None:
    records = parse_bundes_klinik_atlas_xml(BytesIO(SAMPLE_XML))

    assert len(records) == 2
    first = records[0]
    assert first.source_id == "771003"
    assert first.name == "Klinikum Suedstadt Rostock"
    assert first.postal_code == "18059"
    assert first.longitude == 12.107577323914
    assert first.latitude == 54.071629513465
    assert first.emergency_level == 2
    assert first.confirmed_emergency is True
    assert first.severe_injury_care is True
    assert first.children_emergency_level == 1
    assert first.stroke_unit is True

    assert records[1].emergency_level == 3
    assert records[1].emergency_level_not_agreed is True
    assert records[1].confirmed_emergency is False


def test_hospital_access_labels_only_source_backed_capabilities() -> None:
    access = HospitalAccess(
        property_id=1,
        facility_id=2,
        source_id="771003",
        name="Klinikum Suedstadt Rostock",
        street="Suedring 81",
        postal_code="18059",
        city="Rostock",
        facility_url="https://example.test",
        carrier_type="oeffentlich",
        is_children_hospital=True,
        air_distance_km=8.4,
        emergency_level=2,
        severe_injury_care=True,
        children_emergency_level=1,
        specialist_emergency_care=False,
        stroke_unit=True,
        chest_pain_unit=False,
    )

    assert access.facility_type_label_de == "Kinderklinik"
    assert access.emergency_level_label_de == "Notfallstufe 2 · Erweiterte Notfallversorgung"
    assert access.capability_labels_de == (
        "Notfallstufe 2 · Erweiterte Notfallversorgung",
        "Schwerverletztenversorgung",
        "Kinder-Notfallstufe 1",
        "Stroke Unit",
    )


def test_nearest_confirmed_emergency_query_uses_postgis_and_explicit_tier() -> None:
    statement = nearest_confirmed_emergency_stmt({11, 12})
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "ST_Distance" in sql
    assert "hospital_facilities" in sql
    assert "emergency_level" in sql
    assert "emergency_level_not_agreed" in sql
    assert "row_number() OVER" in sql


def test_nearest_hospital_query_does_not_require_emergency_capability() -> None:
    statement = nearest_hospital_stmt({11})
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert "ST_Distance" in sql
    assert "hospital_facilities" in sql
    assert "nearest_hospital_candidates" in sql
    assert "row_number() OVER" in sql


def test_generic_hospital_access_does_not_invent_emergency_label() -> None:
    access = HospitalAccess(
        property_id=1,
        facility_id=3,
        source_id="999999",
        name="Beispielklinik",
        street="Test 1",
        postal_code="10115",
        city="Berlin",
        facility_url=None,
        carrier_type="freigemeinnuetzig",
        is_children_hospital=False,
        air_distance_km=2.5,
        emergency_level=None,
        severe_injury_care=None,
        children_emergency_level=None,
        specialist_emergency_care=None,
        stroke_unit=None,
        chest_pain_unit=None,
    )

    assert access.facility_type_label_de == "Krankenhausstandort"
    assert access.emergency_level_label_de is None
    assert access.capability_labels_de == ()
