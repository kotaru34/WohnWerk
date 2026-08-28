from decimal import Decimal

from app.property_acquisition import (
    PROPERTY_MAX_PRICE_EUR,
    PROPERTY_MIN_PRICE_EUR,
    PROPERTY_VISIBILITY_POLICY,
    annotate_property_items_by_budget,
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
    assert PROPERTY_MIN_PRICE_EUR == Decimal(30000)
    assert PROPERTY_MAX_PRICE_EUR == Decimal(300000)
    assert property_budget_decision(PROPERTY_MIN_PRICE_EUR).accepted is True
    assert property_budget_decision(PROPERTY_MAX_PRICE_EUR).accepted is True
    assert property_budget_decision(Decimal("29999.99")).reason == "price_below_min"
    assert property_budget_decision(Decimal("300000.01")).reason == "price_above_max"
    assert property_budget_decision(None).reason == "price_unknown"


def test_property_visibility_annotation_keeps_every_crawler_item() -> None:
    items = [
        _item(Decimal(30000), "min"),
        _item(Decimal(120000), "family-budget"),
        _item(Decimal(240000), "reserve"),
        _item(Decimal(300000), "max"),
        _item(Decimal(1200), "fake-low"),
        _item(Decimal(349000), "high"),
        _item(None, "unknown"),
    ]

    counts = annotate_property_items_by_budget(items)

    assert len(items) == 7
    assert counts == {
        "accepted": 4,
        "price_unknown": 1,
        "price_below_min": 1,
        "price_above_max": 1,
    }
    by_id = {item.source_listing_id: item.raw_payload for item in items}
    assert by_id["family-budget"]["product_visible"] is True
    assert by_id["reserve"]["product_visible"] is True
    assert by_id["fake-low"]["product_visible"] is False
    assert by_id["high"]["product_visible"] is False
    assert by_id["unknown"]["product_visible"] is False
    assert all(
        payload["product_visibility_policy"] == PROPERTY_VISIBILITY_POLICY
        for payload in by_id.values()
    )


def test_budget_filter_is_only_for_expensive_enrichment() -> None:
    items = [
        _item(Decimal(120000), "accepted"),
        _item(Decimal(349000), "high"),
        _item(None, "unknown"),
    ]

    accepted, counts = filter_property_items_by_budget(items)

    assert [item.source_listing_id for item in accepted] == ["accepted"]
    assert len(items) == 3
    assert counts["accepted"] == 1
    assert items[1].raw_payload["product_visible"] is False
    assert items[2].raw_payload["product_visibility_reason"] == "price_unknown"
