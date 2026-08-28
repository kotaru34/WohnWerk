from decimal import Decimal

from app.property_acquisition import (
    PROPERTY_MAX_PRICE_EUR,
    PROPERTY_MIN_PRICE_EUR,
    filter_property_items_by_budget,
    property_budget_decision,
)
from app.sources.base import RawProperty


def _item(price: Decimal | None, listing_id: str) -> RawProperty:
    return RawProperty(
        source_listing_id=listing_id,
        url=f"https://example.test/{listing_id}",
        title=listing_id,
        price_eur=price,
    )


def test_property_budget_boundaries_are_inclusive() -> None:
    assert property_budget_decision(PROPERTY_MIN_PRICE_EUR).accepted is True
    assert property_budget_decision(PROPERTY_MAX_PRICE_EUR).accepted is True
    assert property_budget_decision(Decimal("29999.99")).reason == "price_below_min"
    assert property_budget_decision(Decimal("150000.01")).reason == "price_above_max"
    assert property_budget_decision(None).reason == "price_unknown"


def test_property_budget_filter_rejects_unknown_and_outside_prices() -> None:
    items = [
        _item(Decimal(30000), "min"),
        _item(Decimal(120000), "inside"),
        _item(Decimal(150000), "max"),
        _item(Decimal(1200), "fake-low"),
        _item(Decimal(349000), "high"),
        _item(None, "unknown"),
    ]

    accepted, counts = filter_property_items_by_budget(items)

    assert [item.source_listing_id for item in accepted] == ["min", "inside", "max"]
    assert counts == {
        "accepted": 3,
        "price_unknown": 1,
        "price_below_min": 1,
        "price_above_max": 1,
    }
    assert all(item.raw_payload.get("acquisition_policy") for item in accepted)
