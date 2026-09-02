import json
from decimal import Decimal

from starlette.requests import Request

from app.house_filters import (
    BASE_HOUSE_FILTERS,
    COOKIE_NAME,
    HouseFilters,
    house_filter_summary,
    load_house_filters,
    resolve_house_filters,
)


def _request(query: str = "", cookie_payload: dict | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookie_payload is not None:
        cookie = f"{COOKIE_NAME}={json.dumps(cookie_payload, separators=(',', ':'))}"
        headers.append((b"cookie", cookie.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/houses",
            "query_string": query.encode(),
            "headers": headers,
        }
    )


def test_house_filters_start_empty() -> None:
    filters = load_house_filters(_request())

    assert filters == BASE_HOUSE_FILTERS
    assert filters == HouseFilters()
    assert filters.ort == ""
    assert filters.radius_km is None
    assert filters.preis_von is None
    assert filters.preis_bis is None
    assert filters.wohn_von is None
    assert filters.wohn_bis is None
    assert filters.nutz_von is None
    assert filters.nutz_bis is None
    assert filters.grund_von is None
    assert filters.grund_bis is None


def test_house_filters_restore_saved_browser_values() -> None:
    saved = HouseFilters(
        ort="Graz",
        radius_km=Decimal(50),
        preis_von=Decimal(40000),
        preis_bis=Decimal(140000),
        wohn_von=Decimal(100),
        wohn_bis=Decimal(180),
        nutz_von=Decimal(120),
        nutz_bis=Decimal(240),
        grund_von=Decimal(500),
        grund_bis=None,
    )
    filters = load_house_filters(_request(cookie_payload=saved.as_cookie_payload()))

    assert filters == saved


def test_explicit_house_filter_query_overrides_saved_cookie() -> None:
    request = _request(
        "ort=Salzburg&radius_km=50&preis_bis=120000&wohn_von=95&nutz_von=110&grund_von=350",
        cookie_payload=HouseFilters(
            ort="Graz",
            radius_km=Decimal(25),
            preis_von=Decimal(50000),
        ).as_cookie_payload(),
    )
    filters = resolve_house_filters(
        request,
        ort="Salzburg",
        radius_km=Decimal(50),
        preis_von=None,
        preis_bis=Decimal(120000),
        wohn_von=Decimal(95),
        wohn_bis=None,
        nutz_von=Decimal(110),
        nutz_bis=None,
        grund_von=Decimal(350),
        grund_bis=None,
    )

    assert filters.ort == "Salzburg"
    assert filters.radius_km == Decimal(50)
    assert filters.preis_von is None
    assert filters.preis_bis == Decimal(120000)
    assert filters.wohn_von == Decimal(95)
    assert filters.nutz_von == Decimal(110)
    assert filters.grund_von == Decimal(350)


def test_house_radius_without_location_is_ignored() -> None:
    request = _request("radius_km=50")

    filters = resolve_house_filters(
        request,
        ort="",
        radius_km=Decimal(50),
        preis_von=None,
        preis_bis=None,
        wohn_von=None,
        wohn_bis=None,
        nutz_von=None,
        nutz_bis=None,
        grund_von=None,
        grund_bis=None,
    )

    assert filters.ort == ""
    assert filters.radius_km is None


def test_invalid_saved_radius_is_ignored() -> None:
    filters = load_house_filters(
        _request(
            cookie_payload={
                "ort": "Salzburg",
                "radius_km": "999",
            }
        )
    )

    assert filters.ort == "Salzburg"
    assert filters.radius_km is None


def test_house_filter_summary_includes_radius() -> None:
    assert (
        house_filter_summary(HouseFilters(ort="Salzburg", radius_km=Decimal(50)))
        == "Salzburg · Umkreis 50 km"
    )


def test_house_filter_reset_clears_saved_filters() -> None:
    request = _request(
        "filter_reset=1",
        cookie_payload=HouseFilters(
            ort="Salzburg",
            radius_km=Decimal(50),
            preis_bis=Decimal(90000),
        ).as_cookie_payload(),
    )
    filters = resolve_house_filters(
        request,
        ort="",
        radius_km=None,
        preis_von=None,
        preis_bis=None,
        wohn_von=None,
        wohn_bis=None,
        nutz_von=None,
        nutz_bis=None,
        grund_von=None,
        grund_bis=None,
    )

    assert filters == HouseFilters()
