"""Deterministic tests of street-address verification and settings-save caching."""

from types import SimpleNamespace

import httpx
import pytest

from app import workplace
from app.property_location_filter import PropertyFilterCenter
from app.workplace_geocoding import (
    _comparable,
    geocode_german_workplace,
    parse_german_street_address,
    validate_address_result,
)

POSTAL = PropertyFilterCenter(longitude=13.737, latitude=51.050)
EXACT = {
    "lat": "51.0504",
    "lon": "13.7381",
    "address": {
        "country_code": "de",
        "postcode": "01067",
        "road": "Musterstraße",
        "house_number": "1",
    },
}


def test_street_address_parser_requires_full_street_number_plz_city() -> None:
    address = parse_german_street_address("Musterstraße 1, 01067 Dresden")
    assert address is not None
    assert (address.road, address.house_number, address.postal_code, address.city) == (
        "Musterstraße", "1", "01067", "Dresden"
    )
    assert parse_german_street_address("01067 Dresden") is None
    assert parse_german_street_address("Musterstraße, 01067 Dresden") is None
    assert parse_german_street_address("Musterstraße 1, 01067 Dresden, DE") is None
    assert _comparable("Musterstr.") == _comparable("Musterstraße")


@pytest.mark.parametrize(
    "changes",
    [
        {"address": {**EXACT["address"], "country_code": "at"}},
        {"address": {**EXACT["address"], "postcode": "01069"}},
        {"address": {**EXACT["address"], "road": "Anderestrasse"}},
        {"address": {**EXACT["address"], "house_number": "11"}},
        {"address": {**EXACT["address"], "house_number": None}},
        {"lat": "NaN"},
        {"lat": "52.0"},
        {"lon": "nan"},
    ],
)
def test_geocoder_rejects_unverified_wrong_address(changes: dict) -> None:
    address = parse_german_street_address("Musterstraße 1, 01067 Dresden")
    assert address is not None
    assert validate_address_result(
        {**EXACT, **changes}, requested=address, postal_centroid=POSTAL
    ) is None


def test_geocoder_accepts_only_verified_single_manual_query(monkeypatch) -> None:
    monkeypatch.setattr("app.workplace_geocoding._throttle_public_request", lambda: None)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/search"
        assert request.url.params["countrycodes"] == "de"
        assert request.url.params["limit"] == "5"
        assert request.url.params["addressdetails"] == "1"
        assert request.url.params["q"].startswith("Musterstraße 1, 01067 Dresden")
        return httpx.Response(200, json=[EXACT])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    address = parse_german_street_address("Musterstraße 1, 01067 Dresden")
    assert address is not None
    result = geocode_german_workplace(
        address,
        postal_centroid=POSTAL,
        base_url="https://nominatim.openstreetmap.org",
        user_agent="WohnWerk/0.4 (example.org/contact)",
        client=client,
    )
    assert result == PropertyFilterCenter(longitude=13.7381, latitude=51.0504)
    assert len(calls) == 1


def test_geocoder_rejects_conflicting_precise_candidates(monkeypatch) -> None:
    monkeypatch.setattr("app.workplace_geocoding._throttle_public_request", lambda: None)
    other = {**EXACT, "lon": "13.751"}
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=[EXACT, other])
    ))
    address = parse_german_street_address("Musterstraße 1, 01067 Dresden")
    assert address is not None
    assert geocode_german_workplace(
        address,
        postal_centroid=POSTAL,
        base_url="https://nominatim.openstreetmap.org",
        user_agent="WohnWerk/0.4 (example.org/contact)",
        client=client,
    ) is None


def test_geocoder_fails_closed_on_provider_outage(monkeypatch) -> None:
    monkeypatch.setattr("app.workplace_geocoding._throttle_public_request", lambda: None)
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(429)
    ))
    address = parse_german_street_address("Musterstraße 1, 01067 Dresden")
    assert address is not None
    assert geocode_german_workplace(
        address,
        postal_centroid=POSTAL,
        base_url="https://nominatim.openstreetmap.org",
        user_agent="WohnWerk/0.4 (example.org/contact)",
        client=client,
    ) is None


def test_workplace_resolution_keeps_centroid_when_house_evidence_fails(monkeypatch):
    monkeypatch.setattr(workplace, "get_settings", lambda: SimpleNamespace(
        workplace_geocoding_enabled=True,
        workplace_geocoding_base_url="https://nominatim.openstreetmap.org",
        workplace_geocoding_user_agent="WohnWerk/test",
        workplace_geocoding_timeout_seconds=2,
        workplace_geocoding_max_postal_centroid_km=15,
    ))
    monkeypatch.setattr(workplace, "resolve_property_filter_center", lambda *_a, **_k: POSTAL)
    monkeypatch.setattr(workplace, "_postal_city", lambda *_a, **_k: "Dresden")
    monkeypatch.setattr(workplace, "geocode_german_workplace", lambda *_a, **_k: None)
    result = workplace.resolve_candidate_workplace(
        object(), country_code="DE", input_text="Musterstraße 1, 01067 Dresden"
    )
    assert result.center == POSTAL
    assert result.method == "street_address_unverified"
    assert result.source == workplace.GEONAMES_SOURCE

    monkeypatch.setattr(workplace, "geocode_german_workplace", lambda *_a, **_k: (
        PropertyFilterCenter(longitude=13.7381, latitude=51.0504)
    ))
    verified = workplace.resolve_candidate_workplace(
        object(), country_code="DE", input_text="Musterstraße 1, 01067 Dresden"
    )
    assert verified.method == "verified_street_address"
    assert verified.center.longitude == 13.7381
    assert verified.source == "OpenStreetMap/Nominatim"


def test_identical_workplace_save_reuses_geocoder_cache(monkeypatch) -> None:
    row = SimpleNamespace(
        country_code="DE", input_text="Musterstraße 1, 01067 Dresden",
        resolution_method="verified_street_address",
    )
    monkeypatch.setattr(workplace, "load_candidate_workplace", lambda *_a: row)
    monkeypatch.setattr(workplace, "get_settings", lambda: SimpleNamespace(
        workplace_geocoding_enabled=True,
    ))
    monkeypatch.setattr(workplace, "resolve_candidate_workplace", lambda *_a, **_k: (
        pytest.fail("unchanged workplace must not query database or geocoder")
    ))
    assert workplace.save_candidate_workplace(
        object(), 1, country_code="DE",
        input_text="Musterstraße 1, 01067 Dresden", commit=False
    ) is row


def test_existing_postal_centroid_is_upgraded_once_after_geocoder_opt_in(monkeypatch):
    row = SimpleNamespace(
        country_code="DE", input_text="Musterstraße 1, 01067 Dresden",
        resolution_method="explicit_postal_centroid",
    )
    calls = []
    monkeypatch.setattr(workplace, "load_candidate_workplace", lambda *_a: row)
    monkeypatch.setattr(workplace, "get_settings", lambda: SimpleNamespace(
        workplace_geocoding_enabled=True,
    ))

    def resolve(*_args, **_kwargs):
        calls.append(1)
        return workplace.WorkplaceResolution(
            country_code="DE", input_text="Musterstraße 1, 01067 Dresden",
            postal_code="01067", city="Dresden", center=POSTAL,
            source=workplace.GEONAMES_SOURCE, method="street_address_unverified",
            error=None,
        )

    monkeypatch.setattr(workplace, "resolve_candidate_workplace", resolve)
    workplace.save_candidate_workplace(
        object(), 1, country_code="DE",
        input_text="Musterstraße 1, 01067 Dresden", commit=False
    )
    workplace.save_candidate_workplace(
        object(), 1, country_code="DE",
        input_text="Musterstraße 1, 01067 Dresden", commit=False
    )
    assert len(calls) == 1
    assert row.resolution_method == "street_address_unverified"
