from decimal import Decimal

from app.property_acquisition import (
    PROPERTY_DE_MAX_PRICE_EUR,
    PROPERTY_MAX_PRICE_EUR,
    PROPERTY_MIN_PRICE_EUR,
    PROPERTY_VISIBILITY_POLICY,
    annotate_property_items_by_budget,
    filter_property_items_by_budget,
    property_budget_decision,
)
from app.sources.base import RawProperty


def _item(
    price: Decimal | None,
    listing_id: str,
    *,
    country_code: str | None = None,
    auction: bool = False,
) -> RawProperty:
    payload = {}
    if country_code is not None:
        payload["country_code"] = country_code
    if auction:
        payload["auction_detected"] = True
        payload["auction_evidence"] = ["zwangsversteigerung"]
    return RawProperty(
        source_listing_id=listing_id,
        url=f"https://example.test/{listing_id}",
        title=listing_id,
        price_eur=price,
        raw_payload=payload,
    )


def test_visibility_policy_marker_stays_compatible_with_existing_at_observations() -> None:
    assert PROPERTY_VISIBILITY_POLICY == "property-product-visibility-2026-08-28-v1"


def test_property_budget_boundaries_preserve_at_and_apply_de_ceiling() -> None:
    assert PROPERTY_MIN_PRICE_EUR == Decimal(30000)
    assert PROPERTY_MAX_PRICE_EUR == Decimal(300000)
    assert PROPERTY_DE_MAX_PRICE_EUR == Decimal(200000)

    assert property_budget_decision(PROPERTY_MIN_PRICE_EUR).accepted is True
    assert property_budget_decision(PROPERTY_MAX_PRICE_EUR).accepted is True
    assert property_budget_decision(Decimal("29999.99")).reason == "price_below_min"
    assert property_budget_decision(Decimal("300000.01")).reason == "price_above_max"
    assert property_budget_decision(None).reason == "price_unknown"

    assert property_budget_decision(Decimal(200000), country_code="DE").accepted is True
    assert (
        property_budget_decision(Decimal("200000.01"), country_code="DE").reason
        == "price_above_max"
    )
    assert property_budget_decision(Decimal(240000), country_code="AT").accepted is True


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
        "auction": 0,
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


def test_de_historical_price_above_200k_is_locally_rejected_without_removal() -> None:
    item = _item(Decimal(240000), "de-high", country_code="DE")

    counts = annotate_property_items_by_budget([item])

    assert counts["price_above_max"] == 1
    assert item.raw_payload["product_visible"] is False
    assert item.raw_payload["product_visibility_reason"] == "price_above_max"
    assert item.raw_payload["product_price_max_eur"] == "200000"


def test_explicit_auction_is_locally_rejected_with_reason_evidence() -> None:
    item = _item(Decimal(120000), "auction", country_code="DE", auction=True)

    counts = annotate_property_items_by_budget([item])

    assert counts["accepted"] == 1
    assert counts["auction"] == 1
    assert item.raw_payload["product_visible"] is False
    assert item.raw_payload["product_visibility_reason"] == "auction"
    assert item.raw_payload["product_visibility_reasons"] == ["auction"]
    assert item.raw_payload["auction_evidence"] == ["zwangsversteigerung"]


def test_budget_filter_skips_auction_and_out_of_budget_expensive_enrichment() -> None:
    items = [
        _item(Decimal(120000), "accepted", country_code="DE"),
        _item(Decimal(120000), "auction", country_code="DE", auction=True),
        _item(Decimal(240000), "de-high", country_code="DE"),
        _item(None, "unknown", country_code="DE"),
    ]

    accepted, counts = filter_property_items_by_budget(items)

    assert [item.source_listing_id for item in accepted] == ["accepted"]
    assert len(items) == 4
    assert counts["accepted"] == 2
    assert counts["auction"] == 1
    assert items[1].raw_payload["product_visibility_reason"] == "auction"
    assert items[2].raw_payload["product_visibility_reason"] == "price_above_max"
    assert items[3].raw_payload["product_visibility_reason"] == "price_unknown"
