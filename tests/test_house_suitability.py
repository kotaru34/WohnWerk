from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.house_suitability import (
    accepted_property_condition,
    matches_de_plz_blacklist,
    parse_de_plz_blacklist,
    rejected_property_condition,
    rejection_reasons_for_property,
)
from app.models import Property


def test_plz_blacklist_normalizes_exact_and_mask_rules() -> None:
    assert parse_de_plz_blacklist("01067, 0XXXX\n12xXx; 01067") == (
        "01067",
        "0xxxx",
        "12xxx",
    )


@pytest.mark.parametrize("value", ["0106", "010678", "0***x", "Berlin", "01x 67"])
def test_plz_blacklist_rejects_invalid_rules(value: str) -> None:
    with pytest.raises(ValueError):
        parse_de_plz_blacklist(value)


def test_plz_blacklist_matches_one_digit_per_x() -> None:
    masks = ("0xxxx", "10115")

    assert matches_de_plz_blacklist("01067", masks) is True
    assert matches_de_plz_blacklist("09999", masks) is True
    assert matches_de_plz_blacklist("10115", masks) is True
    assert matches_de_plz_blacklist("11011", masks) is False
    assert matches_de_plz_blacklist(None, masks) is False


def test_catalog_conditions_keep_blacklist_local_and_explainable() -> None:
    accepted = select(Property.id).where(accepted_property_condition(("0xxxx",)))
    rejected = select(Property.id).where(rejected_property_condition(("0xxxx",)))
    accepted_compiled = accepted.compile(dialect=postgresql.dialect())
    rejected_compiled = rejected.compile(dialect=postgresql.dialect())
    accepted_sql = str(accepted_compiled)
    rejected_sql = str(rejected_compiled)

    assert "properties.postal_code LIKE" in accepted_sql
    assert "properties.postal_code LIKE" in rejected_sql
    assert "property_listings" in accepted_sql
    assert "property_listings" in rejected_sql
    assert "product_visibility_policy" in accepted_compiled.params.values()
    assert "product_visibility_policy" in rejected_compiled.params.values()


def test_rejection_reasons_can_accumulate_source_and_plz_rules() -> None:
    row = Property(
        id=7,
        title="Zwangsversteigerung Einfamilienhaus",
        postal_code="01067",
        price_eur=Decimal(240000),
    )

    reasons = rejection_reasons_for_property(
        row,
        country_code="DE",
        plz_blacklist=("0xxxx",),
        source_payloads=(
            {
                "product_visible": False,
                "product_visibility_reasons": ["auction", "price_above_max"],
            },
        ),
    )

    assert [reason.code for reason in reasons] == [
        "price_above_max",
        "auction",
        "plz_blacklist",
    ]
    assert [reason.label_de for reason in reasons] == [
        "Preis über Budget",
        "Versteigerung",
        "PLZ 01067 auf Sperrliste",
    ]


def test_austria_does_not_apply_german_plz_blacklist() -> None:
    row = Property(
        id=8,
        title="Haus",
        postal_code="01067",
        price_eur=Decimal(120000),
    )

    reasons = rejection_reasons_for_property(
        row,
        country_code="AT",
        plz_blacklist=("0xxxx",),
        source_payloads=({"product_visible": True},),
    )

    assert all(reason.code != "plz_blacklist" for reason in reasons)


def test_hospital_distance_policy_uses_confirmed_emergency_and_complete_dataset() -> None:
    accepted = select(Property.id).where(
        accepted_property_condition(
            max_hospital_distance_km=Decimal(30),
            hospital_fail_closed=False,
        )
    )
    rejected = select(Property.id).where(
        rejected_property_condition(
            max_hospital_distance_km=Decimal(30),
            hospital_fail_closed=False,
        )
    )
    accepted_sql = str(accepted.compile(dialect=postgresql.dialect()))
    rejected_sql = str(rejected.compile(dialect=postgresql.dialect()))

    for sql in (accepted_sql, rejected_sql):
        assert "hospital_dataset_states" in sql
        assert "hospital_facilities" in sql
        assert "ST_DWithin" in sql
        assert "coverage_status" in sql
        assert "emergency_level" in sql
        assert "emergency_level_not_agreed" in sql


def test_hospital_rejection_reason_is_explainable_without_inventing_capability() -> None:
    row = Property(
        id=9,
        title="Haus",
        postal_code="10115",
        price_eur=Decimal(120000),
    )

    reasons = rejection_reasons_for_property(
        row,
        country_code="DE",
        plz_blacklist=(),
        source_payloads=({"product_visible": True},),
        max_hospital_distance_km=Decimal(30),
        hospital_distance_km=42.25,
    )

    assert [reason.code for reason in reasons] == ["hospital_too_far"]
    assert "42.2 km" in reasons[0].label_de
    assert "30 km" in reasons[0].label_de


def test_hospital_unknown_is_fail_open_unless_explicitly_requested() -> None:
    row = Property(
        id=10,
        title="Haus",
        postal_code="10115",
        price_eur=Decimal(120000),
    )

    fail_open = rejection_reasons_for_property(
        row,
        country_code="DE",
        plz_blacklist=(),
        source_payloads=({"product_visible": True},),
        max_hospital_distance_km=Decimal(30),
        hospital_fail_closed=False,
        hospital_distance_km=None,
    )
    fail_closed = rejection_reasons_for_property(
        row,
        country_code="DE",
        plz_blacklist=(),
        source_payloads=({"product_visible": True},),
        max_hospital_distance_km=Decimal(30),
        hospital_fail_closed=True,
        hospital_distance_km=None,
    )

    assert all(reason.code != "hospital_unknown" for reason in fail_open)
    assert [reason.code for reason in fail_closed] == ["hospital_unknown"]


def test_austria_rejection_explanations_ignore_german_hospital_policy() -> None:
    row = Property(
        id=11,
        title="Haus",
        postal_code="5020",
        price_eur=Decimal(120000),
    )

    reasons = rejection_reasons_for_property(
        row,
        country_code="AT",
        plz_blacklist=(),
        source_payloads=({"product_visible": True},),
        max_hospital_distance_km=Decimal(1),
        hospital_fail_closed=True,
        hospital_distance_km=None,
    )

    assert all(not reason.code.startswith("hospital_") for reason in reasons)
