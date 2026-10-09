"""Opt-in, single-address OSM geocoding for a manually saved German workplace.

Never promote a street/PLZ centroid to an exact workplace coordinate without
Nominatim returning matching country, postcode, road and house number evidence.
Public Nominatim must never be used for property batch geocoding.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from math import asin, cos, isfinite, radians, sin, sqrt

import httpx

from app.property_location_filter import PropertyFilterCenter


@dataclass(frozen=True, slots=True)
class StreetAddress:
    road: str
    house_number: str
    postal_code: str
    city: str


_STREET_ADDRESS = re.compile(
    r"^(?P<road>[^,]{3,160}?)\s+(?P<number>\d{1,4}\s?[a-zA-Z]?)\s*,\s*"
    r"(?P<postal>\d{5})\s+(?P<city>[^,]{2,100})$"
)
_THROTTLE_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0


def parse_german_street_address(value: str) -> StreetAddress | None:
    match = _STREET_ADDRESS.fullmatch(" ".join(value.split()))
    if not match:
        return None
    return StreetAddress(
        road=match.group("road"),
        house_number=match.group("number").replace(" ", ""),
        postal_code=match.group("postal"),
        city=match.group("city"),
    )


def _comparable(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    value = re.sub(r"str\.?$", "strasse", value)
    value = re.sub(r"[^a-z0-9]", "", value)
    return value


def _great_circle_km(left: PropertyFilterCenter, right: PropertyFilterCenter) -> float:
    lat1, lat2 = radians(left.latitude), radians(right.latitude)
    value = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * (
        sin(radians(right.longitude - left.longitude) / 2) ** 2
    )
    return 12742.0 * asin(sqrt(min(1.0, value)))


def validate_address_result(
    value: object,
    *,
    requested: StreetAddress,
    postal_centroid: PropertyFilterCenter,
    max_centroid_distance_km: float = 15.0,
) -> PropertyFilterCenter | None:
    if not isinstance(value, dict) or not isinstance(value.get("address"), dict):
        return None
    address = value["address"]
    if (
        str(address.get("country_code", "")).casefold() != "de"
        or str(address.get("postcode", "")) != requested.postal_code
        or _comparable(str(address.get("house_number", "")))
        != _comparable(requested.house_number)
        or _comparable(str(address.get("road", ""))) != _comparable(requested.road)
    ):
        return None

    try:
        latitude = float(value["lat"])
        longitude = float(value["lon"])
    except (KeyError, ValueError, TypeError):
        return None
    if not (
        isfinite(latitude) and isfinite(longitude)
        and 47.2 <= latitude <= 55.1 and 5.8 <= longitude <= 15.1
    ):
        return None
    point = PropertyFilterCenter(longitude=longitude, latitude=latitude)
    if _great_circle_km(postal_centroid, point) > max_centroid_distance_km:
        return None
    return point


def _throttle_public_request() -> None:
    """Best-effort per-process global rate limit for manually submitted addresses."""
    global _LAST_REQUEST_AT
    with _THROTTLE_LOCK:
        pause = max(0.0, 1.1 - (time.monotonic() - _LAST_REQUEST_AT))
        if pause:
            time.sleep(pause)
        _LAST_REQUEST_AT = time.monotonic()


def geocode_german_workplace(
    requested: StreetAddress,
    *,
    postal_centroid: PropertyFilterCenter,
    base_url: str,
    user_agent: str,
    timeout_seconds: float = 5.0,
    max_centroid_distance_km: float = 15.0,
    client: httpx.Client | None = None,
) -> PropertyFilterCenter | None:
    """Make at most one manual search; return None for any unverified result.

    Only explicit opt-in calls may invoke this function. A caller must cache
    both a positive result and a failed attempt for the same address.
    """
    if not user_agent.strip() or not base_url.startswith("https://"):
        return None
    params = {
        "q": f"{requested.road} {requested.house_number}, "
        f"{requested.postal_code} {requested.city}, Deutschland",
        "countrycodes": "de",
        "format": "jsonv2",
        "addressdetails": "1",
        "limit": "5",
    }
    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": user_agent, "Accept-Language": "de"},
        )
    try:
        _throttle_public_request()
        response = client.get(base_url.rstrip("/") + "/search", params=params)
        response.raise_for_status()
        if response.status_code != 200 or response.is_redirect:
            return None
        payload = response.json()
        if not isinstance(payload, list):
            return None
        verified = [
            point
            for item in payload[:5]
            if (point := validate_address_result(
                item,
                requested=requested,
                postal_centroid=postal_centroid,
                max_centroid_distance_km=max_centroid_distance_km,
            )) is not None
        ]
        # Conflicting precise candidates are not arbitrarily selected.
        if not verified or any(
            _great_circle_km(verified[0], other) > 0.25 for other in verified[1:]
        ):
            return None
        return verified[0]
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if owns_client:
            client.close()
