from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.sources.base import RawProperty
from app.sources.property.germany import (
    GERMANY_PROPERTY_MAX_PRICE_EUR,
    GERMANY_PROPERTY_MIN_PRICE_EUR,
)

# Legacy/Austria product behavior remains unchanged. Germany has its own current target.
PROPERTY_MIN_PRICE_EUR = Decimal(30000)
PROPERTY_MAX_PRICE_EUR = Decimal(300000)
PROPERTY_DE_MIN_PRICE_EUR = Decimal(GERMANY_PROPERTY_MIN_PRICE_EUR)
PROPERTY_DE_MAX_PRICE_EUR = Decimal(GERMANY_PROPERTY_MAX_PRICE_EUR)
PROPERTY_VISIBILITY_POLICY = "property-product-visibility-2026-09-27-v2"


@dataclass(frozen=True, slots=True)
class PropertyBudgetDecision:
    accepted: bool
    reason: str


def property_budget_limits(country_code: str | None = None) -> tuple[Decimal, Decimal]:
    if str(country_code or "").strip().upper() == "DE":
        return PROPERTY_DE_MIN_PRICE_EUR, PROPERTY_DE_MAX_PRICE_EUR
    return PROPERTY_MIN_PRICE_EUR, PROPERTY_MAX_PRICE_EUR


def property_budget_decision(
    price_eur: Decimal | None,
    *,
    country_code: str | None = None,
) -> PropertyBudgetDecision:
    minimum, maximum = property_budget_limits(country_code)
    if price_eur is None:
        return PropertyBudgetDecision(False, "price_unknown")
    if price_eur < minimum:
        return PropertyBudgetDecision(False, "price_below_min")
    if price_eur > maximum:
        return PropertyBudgetDecision(False, "price_above_max")
    return PropertyBudgetDecision(True, "accepted")


def property_in_acquisition_budget(item: RawProperty) -> bool:
    country_code = (item.raw_payload or {}).get("country_code")
    return property_budget_decision(item.price_eur, country_code=country_code).accepted


def _product_visibility(
    decision: PropertyBudgetDecision,
    payload: dict,
) -> tuple[bool, str, list[str]]:
    reasons: list[str] = []

    if payload.get("auction_detected") is True:
        reasons.append("auction")

    if not decision.accepted:
        reasons.append(decision.reason)

    if payload.get("original_url_missing") is True:
        reasons.append("source_url_missing")

    if payload.get("source_liveness_required") is True:
        state = payload.get("source_liveness_state")
        if state == "dead":
            reasons.append("source_dead")
        elif state != "live":
            reasons.append("source_liveness_unverified")

    if reasons:
        return False, reasons[0], reasons
    return True, "accepted", []


def annotate_property_items_by_budget(
    items: list[RawProperty],
) -> dict[str, int]:
    """Annotate every crawler observation without removing it from lifecycle storage."""
    counts = {
        "accepted": 0,
        "price_unknown": 0,
        "price_below_min": 0,
        "price_above_max": 0,
        "auction": 0,
    }
    for item in items:
        payload = dict(item.raw_payload)
        country_code = payload.get("country_code")
        decision = property_budget_decision(item.price_eur, country_code=country_code)
        counts[decision.reason] += 1
        if payload.get("auction_detected") is True:
            counts["auction"] += 1

        visible, reason, reasons = _product_visibility(decision, payload)
        minimum, maximum = property_budget_limits(country_code)
        payload["product_visibility_policy"] = PROPERTY_VISIBILITY_POLICY
        payload["product_visible"] = visible
        payload["product_visibility_reason"] = reason
        payload["product_visibility_reasons"] = reasons
        payload["product_price_min_eur"] = str(minimum)
        payload["product_price_max_eur"] = str(maximum)
        item.raw_payload = payload
    return counts


def filter_property_items_by_budget(
    items: list[RawProperty],
) -> tuple[list[RawProperty], dict[str, int]]:
    """Return policy-eligible items for optional expensive source enrichment.

    This helper must never be used to decide which listings are persisted for lifecycle
    accounting. `run_property_source()` stores the complete parsed source corpus.
    """
    counts = annotate_property_items_by_budget(items)
    accepted = [
        item
        for item in items
        if property_in_acquisition_budget(item)
        and (item.raw_payload or {}).get("auction_detected") is not True
    ]
    return accepted, counts
