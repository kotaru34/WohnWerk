from __future__ import annotations

from sqlalchemy import and_, exists, func, or_, select

from app.models import ListingStatus, Property, PropertyListing
from app.property_acquisition import (
    PROPERTY_DE_MAX_PRICE_EUR,
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


def _usable_source_observation_condition():
    original_url_missing = func.coalesce(
        PropertyListing.raw_payload.op("->>")("original_url_missing"),
        "false",
    )
    return original_url_missing != "true"


def _de_property_condition():
    return exists(
        select(PropertyListing.id).where(
            PropertyListing.property_id == Property.id,
            PropertyListing.status == ListingStatus.ACTIVE,
            PropertyListing.raw_payload.is_not(None),
            PropertyListing.raw_payload["country_code"].as_string() == "DE",
        )
    )


def product_visible_property_condition():
    """Return the SQL condition for father-facing property visibility.

    Current source observations are authoritative when they carry the current visibility
    policy. Legacy rows remain available through a canonical-price fallback, but Germany
    applies the current EUR 200k ceiling immediately even to historical observations that
    will never be rediscovered after the narrower acquisition query.
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
            _usable_source_observation_condition(),
            PropertyListing.raw_payload["product_visible"].as_boolean().is_(True),
        )
    )

    is_de = _de_property_condition()
    current_price_window = and_(
        Property.price_eur.is_not(None),
        Property.price_eur >= PROPERTY_MIN_PRICE_EUR,
        or_(
            and_(is_de, Property.price_eur <= PROPERTY_DE_MAX_PRICE_EUR),
            and_(~is_de, Property.price_eur <= PROPERTY_MAX_PRICE_EUR),
        ),
    )
    de_non_auction_title = or_(
        ~is_de,
        ~func.lower(func.coalesce(Property.title, "")).contains("versteigerung"),
    )
    legacy_price_fallback = and_(~any_current_observation, current_price_window)

    return and_(
        de_non_auction_title,
        current_price_window,
        or_(accepted_current_observation, legacy_price_fallback),
    )
