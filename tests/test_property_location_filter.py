from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.house_filters import HouseFilters
from app.models import Property
from app.property_location_filter import (
    PropertyFilterCenter,
    resolve_property_radius_filter,
)


def _sql(condition) -> tuple[str, dict]:
    compiled = select(Property.id).where(condition).compile(
        dialect=postgresql.dialect(),
    )
    return str(compiled), compiled.params


def test_radius_filter_uses_postgis_distance(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.property_location_filter.resolve_property_filter_center",
        lambda _session, _value: PropertyFilterCenter(
            longitude=13.055,
            latitude=47.809,
        ),
    )

    resolved = resolve_property_radius_filter(
        object(),
        HouseFilters(
            ort="Salzburg",
            radius_km=Decimal(50),
        ),
    )

    assert resolved is not None
    assert resolved.error is None

    sql, params = _sql(resolved.condition)
    assert "ST_DWithin" in sql
    assert "ST_MakePoint" in sql
    assert "properties.location IS NOT NULL" in sql
    assert 50000.0 in params.values()
    assert 13.055 in params.values()
    assert 47.809 in params.values()


def test_unresolved_radius_center_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.property_location_filter.resolve_property_filter_center",
        lambda _session, _value: None,
    )

    resolved = resolve_property_radius_filter(
        object(),
        HouseFilters(
            ort="Nicht Vorhanden",
            radius_km=Decimal(50),
        ),
    )

    assert resolved is not None
    assert resolved.error is not None
    assert "Nicht Vorhanden" in resolved.error

    sql, _params = _sql(resolved.condition)
    assert "false" in sql.lower()


def test_radius_filter_is_inactive_without_radius() -> None:
    assert (
        resolve_property_radius_filter(
            object(),
            HouseFilters(ort="Salzburg"),
        )
        is None
    )
