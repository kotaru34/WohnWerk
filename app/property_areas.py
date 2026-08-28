from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Numeric, cast, exists, func, select

from app.models import ListingStatus, Property, PropertyListing


def usable_area_expression():
    """Read only explicitly labelled source Nutzfläche values from active payloads."""
    return cast(
        func.coalesce(
            PropertyListing.raw_payload["detail_usable_area_m2"].as_string(),
            PropertyListing.raw_payload["explicit_usable_area_m2"].as_string(),
        ),
        Numeric(12, 2),
    )


def usable_area_property_condition(
    minimum: Decimal | None,
    maximum: Decimal | None,
):
    if minimum is None and maximum is None:
        return None

    value = usable_area_expression()
    conditions = [
        PropertyListing.property_id == Property.id,
        PropertyListing.status == ListingStatus.ACTIVE,
        PropertyListing.raw_payload.is_not(None),
    ]
    if minimum is not None:
        conditions.append(value >= minimum)
    if maximum is not None:
        conditions.append(value <= maximum)
    return exists(select(PropertyListing.id).where(*conditions))
