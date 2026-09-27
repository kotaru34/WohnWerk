from __future__ import annotations

# Property points derived from postal-code reference data are useful for broad
# radius/distance context, but are not precise enough to select a 100 x 100 m
# broadband raster cell for a specific house.
POSTAL_LOCATION_METHODS = frozenset({"postal_place_mean", "address_mean"})

# These method names are reserved for evidence that locates the actual property
# to an address/parcel-scale point. Current discovery sources do not create such
# a point unless they explicitly provide or resolve one.
PRECISE_PROPERTY_LOCATION_METHODS = frozenset(
    {
        "source_coordinate",
        "address_geocode",
        "manual_exact_point",
    }
)


def internet_location_is_precise(method: str | None) -> bool:
    return (method or "").strip().casefold() in PRECISE_PROPERTY_LOCATION_METHODS
