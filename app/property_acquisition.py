from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.sources.base import RawProperty

PROPERTY_MIN_PRICE_EUR = Decimal(30000)
PROPERTY_MAX_PRICE_EUR = Decimal(300000)
PROPERTY_VISIBILITY_POLICY = "property-product-visibility-2026-08-28-v1"


@dataclass(frozen=True, slots=True)
class PropertyBudgetDecision:
    accepted: bool
    reason: str


def property_budget_decision(price_eur: Decimal | None) -> PropertyBudgetDecision:
    if price_eur is None:
        return PropertyBudgetDecision(False, "price_unknown")
    if price_eur < PROPERTY_MIN_PRICE_EUR:
        return PropertyBudgetDecision(False, "price_below_min")
    if price_eur > PROPERTY_MAX_PRICE_EUR:
        return PropertyBudgetDecision(False, "price_above_max")
    return PropertyBudgetDecision(True, "accepted")


def property_in_acquisition_budget(item: RawProperty) -> bool:
    return property_budget_decision(item.price_eur).accepted


def annotate_property_items_by_budget(
    items: list[RawProperty],
) -> dict[str, int]:
    """Annotate every crawler observation without removing it from lifecycle storage.

    The crawler corpus is intentionally broader than the father-facing product corpus.
    Every parsed listing must still be persisted so reconciliation/continuity can reason
    about what the source currently exposes. Product visibility and expensive enrichment
    are separate concerns and are driven by the explicit source-backed price observation.
    """
    counts = {
        "accepted": 0,
        "price_unknown": 0,
        "price_below_min": 0,
        "price_above_max": 0,
    }
    for item in items:
        decision = property_budget_decision(item.price_eur)
        counts[decision.reason] += 1
        payload = dict(item.raw_payload)
        payload["product_visibility_policy"] = PROPERTY_VISIBILITY_POLICY
        payload["product_visible"] = decision.accepted
        payload["product_visibility_reason"] = decision.reason
        payload["product_price_min_eur"] = str(PROPERTY_MIN_PRICE_EUR)
        payload["product_price_max_eur"] = str(PROPERTY_MAX_PRICE_EUR)
        item.raw_payload = payload
    return counts


def filter_property_items_by_budget(
    items: list[RawProperty],
) -> tuple[list[RawProperty], dict[str, int]]:
    """Return only product-eligible items for optional expensive source enrichment.

    This helper must never be used to decide which listings are persisted for lifecycle
    accounting. `run_property_source()` stores the complete parsed source corpus.
    """
    counts = annotate_property_items_by_budget(items)
    accepted = [item for item in items if property_in_acquisition_budget(item)]
    return accepted, counts
