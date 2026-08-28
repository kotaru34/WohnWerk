from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.sources.base import RawProperty

PROPERTY_MIN_PRICE_EUR = Decimal(30000)
PROPERTY_MAX_PRICE_EUR = Decimal(150000)
PROPERTY_ACQUISITION_POLICY = "property-budget-2026-08-28-v1"


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


def filter_property_items_by_budget(
    items: list[RawProperty],
) -> tuple[list[RawProperty], dict[str, int]]:
    accepted: list[RawProperty] = []
    counts = {
        "accepted": 0,
        "price_unknown": 0,
        "price_below_min": 0,
        "price_above_max": 0,
    }
    for item in items:
        decision = property_budget_decision(item.price_eur)
        counts[decision.reason] += 1
        if decision.accepted:
            payload = dict(item.raw_payload)
            payload["acquisition_policy"] = PROPERTY_ACQUISITION_POLICY
            payload["acquisition_price_min_eur"] = str(PROPERTY_MIN_PRICE_EUR)
            payload["acquisition_price_max_eur"] = str(PROPERTY_MAX_PRICE_EUR)
            item.raw_payload = payload
            accepted.append(item)
    return accepted, counts
