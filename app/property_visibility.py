from __future__ import annotations

from sqlalchemy import and_, exists, or_, select

from app.models import ListingStatus, Property, PropertyListing
from app.property_acquisition import (
    PROPERTY_MAX_PRICE_EUR,
    PROPERTY_MIN_PRICE_EUR,
    PROPERTY_VISIBILITY_POLICY,
)


def _policy_observation_condition():
    return and_(
        PropertyListing.status == ListingStatus.ACTIVE,
        PropertyListing.raw_payload.is_not(None),
        PropertyListing.raw_payload["product_visibility_policy"].as_string()
        == PROPERTY_VISIBILITY_POLICY,
    )


def product_visible_property_condition():
    """Return the SQL condition for father-facing property visibility.

    Current source observations are authoritative when they carry the visibility policy.
    A property is shown if at least one active current observation is explicitly accepted.

    Legacy active listings created before this policy are temporarily allowed to fall back
    to the canonical price so deploying the code does not blank the catalogue before the
    next crawl touches every row. As soon as any active listing for the property carries the
    current policy, that observation becomes authoritative and the legacy fallback stops.
    """
    any_current_observation = exists(
        select(PropertyListing.id).where(
            PropertyListing.property_id == Property.id,
            _policy_observation_condition(),
        )
    )
    accepted_current_observation = exists(
        select(PropertyListing.id).where(
            PropertyListing.property_id == Property.id,
            _policy_observation_condition(),
            PropertyListing.raw_payload["product_visible"].as_boolean().is_(True),
        )
    )
    legacy_price_fallback = and_(
        ~any_current_observation,
        Property.price_eur.is_not(None),
        Property.price_eur >= PROPERTY_MIN_PRICE_EUR,
        Property.price_eur <= PROPERTY_MAX_PRICE_EUR,
    )
    return or_(accepted_current_observation, legacy_price_fallback)
