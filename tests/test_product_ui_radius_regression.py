from decimal import Decimal
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import product_ui
from app.house_filters import HouseFilters


class _StopAfterRadiusFilter(RuntimeError):
    pass


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/houses",
            "headers": [],
            "query_string": b"ort=Salzburg&radius_km=50",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 12345),
        }
    )


def test_active_product_house_route_forwards_radius_to_filter_pipeline(monkeypatch) -> None:
    radius = Decimal(50)
    resolved_radius = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(product_ui, "_profile_or_503", lambda _db: SimpleNamespace(id=1))
    monkeypatch.setattr(product_ui, "novelty_baseline", lambda *_args: object())
    monkeypatch.setattr(product_ui, "_product_property_conditions", list)
    monkeypatch.setattr(product_ui, "property_curation_condition", lambda *_args: True)

    def fake_resolve_house_filters(_request, **kwargs):
        captured["resolver_radius"] = kwargs.get("radius_km")
        return HouseFilters(ort="Salzburg", radius_km=radius)

    def fake_resolve_radius(_db, filters):
        captured["radius_filters"] = filters
        return resolved_radius

    def fake_property_conditions(filters, *, radius_filter=None):
        captured["condition_filters"] = filters
        captured["condition_radius"] = radius_filter
        raise _StopAfterRadiusFilter

    monkeypatch.setattr(product_ui, "resolve_house_filters", fake_resolve_house_filters)
    monkeypatch.setattr(product_ui, "resolve_property_radius_filter", fake_resolve_radius)
    monkeypatch.setattr(product_ui, "_property_filter_conditions", fake_property_conditions)

    route = next(route for route in product_ui.router.routes if route.path == "/houses")
    assert route.endpoint is product_ui.houses_page

    with pytest.raises(_StopAfterRadiusFilter):
        product_ui.houses_page(
            _request(),
            None,
            object(),
            ort="Salzburg",
            radius_km=radius,
        )

    assert captured["resolver_radius"] == radius
    assert captured["radius_filters"] == HouseFilters(ort="Salzburg", radius_km=radius)
    assert captured["condition_filters"] == HouseFilters(ort="Salzburg", radius_km=radius)
    assert captured["condition_radius"] is resolved_radius
