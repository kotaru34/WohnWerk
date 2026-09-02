from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from app.country_scope import _country_href, _switch_markup, normalize_country
from app.postal_codes_de import parse_geonames_de_postal_zip
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
