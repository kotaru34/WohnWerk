import json
from decimal import Decimal

from starlette.requests import Request

from app.house_filters import (
    BASE_HOUSE_FILTERS,
    COOKIE_NAME,
    HouseFilters,
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
        "preis_bis=120000&wohn_von=95&nutz_von=110&grund_von=350",
        cookie_payload=HouseFilters(preis_von=Decimal(50000)).as_cookie_payload(),
    )
    filters = resolve_house_filters(
        request,
        ort="",
        preis_von=None,
        preis_bis=Decimal(120000),
        wohn_von=Decimal(95),
        wohn_bis=None,
        nutz_von=Decimal(110),
        nutz_bis=None,
        grund_von=Decimal(350),
        grund_bis=None,
    )

    assert filters.preis_von is None
    assert filters.preis_bis == Decimal(120000)
    assert filters.wohn_von == Decimal(95)
    assert filters.nutz_von == Decimal(110)
    assert filters.grund_von == Decimal(350)


def test_house_filter_reset_clears_saved_filters() -> None:
    request = _request(
        "filter_reset=1",
        cookie_payload=HouseFilters(preis_bis=Decimal(90000)).as_cookie_payload(),
    )
    filters = resolve_house_filters(
        request,
        ort="",
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
