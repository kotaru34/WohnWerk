from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from app import postal_codes_de
from app.country_scope import _SCOPED_PREFIXES, _country_href, _switch_markup, normalize_country
from app.models import PostalCode
from app.postal_codes_de import GermanPostalCodeRecord, parse_geonames_de_postal_zip
from app.sources.job.adzuna import AdzunaQuery, parse_adzuna_job
from app.sources.job.adzuna_de import _normalize_german_location
from app.sources.job.arbeitsagentur import ArbeitsagenturQuery, parse_arbeitsagentur_job


def _geonames_zip(rows: list[str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("DE.txt", "\n".join(rows) + "\n")
    return buffer.getvalue()


def test_country_switch_normalizes_and_preserves_existing_query() -> None:
    scope = {
        "path": "/houses",
        "query_string": b"sort=price&country=AT&page=2",
    }

    assert normalize_country("de") == "DE"
    assert normalize_country(" at ") == "AT"
    assert normalize_country("CH") is None
    assert _country_href(scope, "DE") == "/houses?sort=price&page=2&country=DE"

    markup = _switch_markup(scope, "DE").decode("utf-8")
    assert "🇩🇪 DE" in markup
    assert "🇦🇹 AT" in markup
    assert 'href="/houses?sort=price&amp;page=2&amp;country=AT"' in markup


def test_country_scope_includes_actual_matches_route() -> None:
    assert "/admin/matches".startswith(_SCOPED_PREFIXES)

    scope = {
        "path": "/admin/matches",
        "query_string": b"radius_km=50&country=AT",
    }
    assert _country_href(scope, "DE") == "/admin/matches?radius_km=50&country=DE"


def test_geonames_de_parser_preserves_leading_zero_and_averages_duplicates() -> None:
    payload = _geonames_zip(
        [
            "DE\t01067\tDresden\tSachsen\tSN\t\t\t\t\t51.0500\t13.7300\t6",
            "DE\t01067\tDresden\tSachsen\tSN\t\t\t\t\t51.0540\t13.7340\t6",
            "DE\t10115\tBerlin\tBerlin\tBE\t\t\t\t\t52.5320\t13.3840\t6",
            "AT\t1010\tWien\tWien\t9\t\t\t\t\t48.2082\t16.3738\t6",
        ]
    )

    records = {record.postal_code: record for record in parse_geonames_de_postal_zip(payload)}

    assert set(records) == {"01067", "10115"}
    assert records["01067"].name == "Dresden"
    assert records["01067"].sample_count == 2
    assert records["01067"].latitude == 51.052
    assert records["01067"].longitude == 13.732


def test_geonames_upsert_batches_large_values(monkeypatch) -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.statements = []
            self.commit_count = 0

        def execute(self, statement):
            self.statements.append(statement)

        def commit(self) -> None:
            self.commit_count += 1

    monkeypatch.setattr(postal_codes_de, "GEONAMES_UPSERT_BATCH_SIZE", 2)

    records = [
        GermanPostalCodeRecord(
            postal_code=f"{10000 + index:05d}",
            name=f"Place {index}",
            longitude=10.0 + index / 1000,
            latitude=50.0 + index / 1000,
            sample_count=1,
        )
        for index in range(5)
    ]
    session = FakeSession()

    assert postal_codes_de.upsert_german_postal_codes(session, records) == 5
    assert len(session.statements) == 3
    assert session.commit_count == 1

    bound_parameter_counts = [len(statement.compile().params) for statement in session.statements]
    assert bound_parameter_counts == [14, 14, 7]


def test_runtime_model_matches_five_digit_postal_migration() -> None:
    assert PostalCode.__table__.c.postal_code.type.length == 5


def test_arbeitsagentur_parser_normalizes_integer_plz_and_coordinates() -> None:
    raw = {
        "refnr": "10000-1234567890-S",
        "titel": "Entwicklungsingenieur Maschinenbau (m/w/d)",
        "beruf": "Ingenieur/in - Maschinenbau",
        "arbeitgeber": "Beispiel GmbH",
        "arbeitsort": {
            "plz": 1067,
            "ort": "Dresden",
            "region": "Sachsen",
            "land": "Deutschland",
            "koordinaten": {"lat": 51.0504, "lon": 13.7373},
        },
        "externeUrl": "https://example.invalid/job/123",
    }

    item = parse_arbeitsagentur_job(
        raw,
        query=ArbeitsagenturQuery("entwicklungsingenieur", "Entwicklungsingenieur"),
    )

    assert item is not None
    assert item.source_listing_id == "arbeitsagentur:10000-1234567890-S"
    assert item.url.endswith("/10000-1234567890-S")
    assert item.locations[0].postal_code == "01067"
    assert item.locations[0].city == "Dresden"
    assert item.raw_payload["latitude"] == 51.0504
    assert item.raw_payload["longitude"] == 13.7373
    assert item.raw_payload["country_code"] == "DE"


def test_adzuna_de_normalizer_understands_five_digit_plz() -> None:
    raw = {
        "id": "123",
        "title": "CAD Konstrukteur",
        "redirect_url": "https://example.invalid/jobs/123",
        "location": {"display_name": "01067 Dresden, Sachsen, Germany"},
        "latitude": 51.0504,
        "longitude": 13.7373,
    }
    item = parse_adzuna_job(
        raw,
        query=AdzunaQuery("cad-konstrukteur", "CAD Konstrukteur"),
    )

    assert item is not None
    normalized = _normalize_german_location(item)
    assert normalized.locations[0].postal_code == "01067"
    assert normalized.locations[0].city == "Dresden"
    assert normalized.raw_payload["country_code"] == "DE"
