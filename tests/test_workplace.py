from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app import workplace
from app.models import Property
from app.property_location_filter import PropertyFilterCenter


def test_extract_explicit_postal_code_from_full_input() -> None:
    assert (
        workplace.extract_explicit_postal_code(
            "DE",
            "Musterstraße 1, 01067 Dresden",
        )
        == "01067"
    )
    with pytest.raises(ValueError, match="muss DE sein"):
        workplace.extract_explicit_postal_code("AT", "5020 Salzburg")


def test_multiple_postal_codes_are_rejected() -> None:
    with pytest.raises(ValueError):
        workplace.extract_explicit_postal_code(
            "DE",
            "01067 Dresden / 10115 Berlin",
        )


def test_workplace_resolution_uses_explicit_country_and_postal_centroid(
    monkeypatch,
) -> None:
    seen: list[tuple[str, str]] = []

    def fake_center(_session, value: str, *, country_code: str | None = None):
        seen.append((value, str(country_code)))
        return PropertyFilterCenter(longitude=13.7373, latitude=51.0504)

    monkeypatch.setattr(workplace, "resolve_property_filter_center", fake_center)
    monkeypatch.setattr(workplace, "_postal_city", lambda *_args, **_kwargs: "Dresden")

    resolved = workplace.resolve_candidate_workplace(
        object(),
        country_code="DE",
        input_text="Musterstraße 1, 01067 Dresden",
    )

    assert seen == [("01067", "DE")]
    assert resolved.postal_code == "01067"
    assert resolved.city == "Dresden"
    assert resolved.center == PropertyFilterCenter(longitude=13.7373, latitude=51.0504)
    assert resolved.method == "explicit_postal_centroid"
    assert resolved.error is None


def test_unresolved_workplace_preserves_unknown_instead_of_inventing_point(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        workplace,
        "resolve_property_filter_center",
        lambda *_args, **_kwargs: None,
    )

    resolved = workplace.resolve_candidate_workplace(
        object(),
        country_code="DE",
        input_text="Unbekannter Firmenstandort",
    )

    assert resolved.center is None
    assert resolved.source is None
    assert resolved.method is None
    assert resolved.error is not None


def test_workplace_distance_sql_is_profile_scoped_and_uses_postgis() -> None:
    statement = workplace.workplace_distance_stmt(7, {11, 12})
    compiled = statement.compile(dialect=postgresql.dialect())

    sql = str(compiled)
    assert "ST_Distance" in sql
    assert "candidate_workplaces.profile_id" in sql
    assert "properties.location IS NOT NULL" in sql
    assert 7 in compiled.params.values()


def test_workplace_distance_is_not_part_of_property_acceptance_predicate() -> None:
    from app.house_suitability import accepted_property_condition

    compiled = select(Property.id).where(accepted_property_condition()).compile(
        dialect=postgresql.dialect()
    )

    assert "candidate_workplaces" not in str(compiled)


def test_graph_coverage_requires_each_country() -> None:
    assert workplace.routing_graph_supports("AT", "AT")
    assert not workplace.routing_graph_supports("DE", "AT")
    assert workplace.routing_graph_supports("DE", "AT,DE")
    assert workplace.routing_graph_supports("AT", "AT,DE")
    assert not workplace.routing_graph_supports(None, "AT,DE")


def test_german_workplace_cannot_route_on_austria_only_graph(monkeypatch) -> None:
    settings = SimpleNamespace(
        routing_enabled=True,
        country_code="DE",
        routing_graph_countries="AT",
    )
    monkeypatch.setattr(workplace, "get_settings", lambda: settings)
    monkeypatch.setattr(workplace, "selected_country", lambda: "DE")
    monkeypatch.setattr(
        workplace, "load_candidate_workplace",
        lambda _session, _profile: SimpleNamespace(country_code="DE"),
    )
    called: list[tuple[int, set[int]]] = []

    def air_only(_session, profile_id, property_ids):
        called.append((profile_id, property_ids))
        return {3: workplace.WorkplaceDistance(property_id=3, air_distance_km=450)}

    monkeypatch.setattr(workplace, "load_workplace_distances", air_only)
    monkeypatch.setattr(
        workplace, "OSRMClient",
        lambda *_args, **_kwargs: pytest.fail("OSRM must not be called for DE on AT graph"),
    )
    result = workplace.load_workplace_distances_for_ui(object(), 9, {3})
    assert called == [(9, {3})]
    assert result[3].road_distance_km is None
    assert result[3].road_duration_minutes is None


def test_cross_border_workplace_needs_both_countries_in_graph(monkeypatch) -> None:
    settings = SimpleNamespace(
        routing_enabled=True,
        country_code="AT",
        routing_graph_countries="AT",
    )
    monkeypatch.setattr(workplace, "get_settings", lambda: settings)
    monkeypatch.setattr(workplace, "selected_country", lambda: "AT")
    monkeypatch.setattr(
        workplace, "load_candidate_workplace",
        lambda _session, _profile: SimpleNamespace(country_code="DE"),
    )
    monkeypatch.setattr(workplace, "load_workplace_distances", lambda *_a, **_kw: {5: "air"})
    monkeypatch.setattr(
        workplace, "OSRMClient",
        lambda *_a, **_kw: pytest.fail("cannot route from AT to DE with AT-only graph"),
    )
    assert workplace.load_workplace_distances_for_ui(object(), 1, {5}) == {5: "air"}
