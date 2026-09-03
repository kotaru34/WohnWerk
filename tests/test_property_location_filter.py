from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app import property_location_filter as plf
from app.house_filters import HouseFilters
from app.models import Property
from app.postal_codes_de import GEONAMES_SOURCE


def _sql(condition) -> tuple[str, dict]:
    compiled = select(Property.id).where(condition).compile(
        dialect=postgresql.dialect(),
    )
    return str(compiled), compiled.params


def test_radius_filter_uses_postgis_distance(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.property_location_filter.resolve_property_filter_center",
        lambda _session, _value: plf.PropertyFilterCenter(
            longitude=13.055,
            latitude=47.809,
        ),
    )

    resolved = plf.resolve_property_radius_filter(
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

    resolved = plf.resolve_property_radius_filter(
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
        plf.resolve_property_radius_filter(
            object(),
            HouseFilters(ort="Salzburg"),
        )
        is None
    )


def test_de_five_digit_postal_code_uses_german_postal_path(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(plf, "selected_country", lambda: "DE")

    def fake_postal_center(_session, postal_code: str, *, country_code: str):
        seen.append((postal_code, country_code))
        return plf.PropertyFilterCenter(longitude=13.7373, latitude=51.0504)

    monkeypatch.setattr(plf, "_postal_center", fake_postal_center)

    resolved = plf.resolve_property_filter_center(object(), "01067")

    assert resolved == plf.PropertyFilterCenter(longitude=13.7373, latitude=51.0504)
    assert seen == [("01067", "DE")]


def test_de_city_uses_geonames_path_not_austrian_resolver(monkeypatch) -> None:
    monkeypatch.setattr(plf, "selected_country", lambda: "DE")
    monkeypatch.setattr(
        plf,
        "_german_locality_center",
        lambda _session, city: (
            plf.PropertyFilterCenter(longitude=13.405, latitude=52.52)
            if city == "Berlin"
            else None
        ),
    )

    def fail_austria_resolver(*_args, **_kwargs):
        raise AssertionError("Austria resolver must not run for DE")

    monkeypatch.setattr(plf, "resolve_locality", fail_austria_resolver)

    resolved = plf.resolve_property_filter_center(object(), "Berlin")

    assert resolved == plf.PropertyFilterCenter(longitude=13.405, latitude=52.52)


def test_de_postal_query_is_scoped_to_geonames_source() -> None:
    class EmptyResult:
        def one_or_none(self):
            return None

    class CapturingSession:
        statement = None

        def execute(self, statement):
            self.statement = statement
            return EmptyResult()

    session = CapturingSession()
    assert plf._postal_center(session, "01067", country_code="DE") is None
    assert session.statement is not None

    compiled = session.statement.compile()
    assert "postal_codes.source" in str(compiled)
    assert GEONAMES_SOURCE in compiled.params.values()
