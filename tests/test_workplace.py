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
    assert workplace.extract_explicit_postal_code("AT", "5020 Salzburg") == "5020"


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
