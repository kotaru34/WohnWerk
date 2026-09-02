from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from fastapi import Request, Response

# v3 is kept for backwards compatibility; the optional radius field is additive.
COOKIE_NAME = "wohnwerk_house_filters_v3"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365
MAX_RADIUS_KM = Decimal(250)
FILTER_QUERY_KEYS = frozenset(
    {
        "ort",
        "radius_km",
        "preis_von",
        "preis_bis",
        "wohn_von",
        "wohn_bis",
        "nutz_von",
        "nutz_bis",
        "grund_von",
        "grund_bis",
    }
)


@dataclass(frozen=True, slots=True)
class HouseFilters:
    ort: str = ""
    radius_km: Decimal | None = None
    preis_von: Decimal | None = None
    preis_bis: Decimal | None = None
    wohn_von: Decimal | None = None
    wohn_bis: Decimal | None = None
    nutz_von: Decimal | None = None
    nutz_bis: Decimal | None = None
    grund_von: Decimal | None = None
    grund_bis: Decimal | None = None

    def as_cookie_payload(self) -> dict[str, str | None]:
        return {
            "ort": self.ort,
            "radius_km": _decimal_text(self.radius_km),
            "preis_von": _decimal_text(self.preis_von),
            "preis_bis": _decimal_text(self.preis_bis),
            "wohn_von": _decimal_text(self.wohn_von),
            "wohn_bis": _decimal_text(self.wohn_bis),
            "nutz_von": _decimal_text(self.nutz_von),
            "nutz_bis": _decimal_text(self.nutz_bis),
            "grund_von": _decimal_text(self.grund_von),
            "grund_bis": _decimal_text(self.grund_bis),
        }


EMPTY_HOUSE_FILTERS = HouseFilters()
BASE_HOUSE_FILTERS = EMPTY_HOUSE_FILTERS


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _safe_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    if not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _safe_radius(value: object, *, has_location: bool) -> Decimal | None:
    if not has_location:
        return None
    parsed = _safe_decimal(value)
    if parsed is None or parsed < 1 or parsed > MAX_RADIUS_KM:
        return None
    return parsed


def _from_mapping(payload: dict[str, object]) -> HouseFilters:
    raw_ort = payload.get("ort")
    ort = raw_ort.strip()[:120] if isinstance(raw_ort, str) else ""
    return HouseFilters(
        ort=ort,
        radius_km=_safe_radius(payload.get("radius_km"), has_location=bool(ort)),
        preis_von=_safe_decimal(payload.get("preis_von")),
        preis_bis=_safe_decimal(payload.get("preis_bis")),
        wohn_von=_safe_decimal(payload.get("wohn_von")),
        wohn_bis=_safe_decimal(payload.get("wohn_bis")),
        nutz_von=_safe_decimal(payload.get("nutz_von")),
        nutz_bis=_safe_decimal(payload.get("nutz_bis")),
        grund_von=_safe_decimal(payload.get("grund_von")),
        grund_bis=_safe_decimal(payload.get("grund_bis")),
    )


def load_house_filters(request: Request) -> HouseFilters:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return EMPTY_HOUSE_FILTERS
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return EMPTY_HOUSE_FILTERS
    if not isinstance(payload, dict):
        return EMPTY_HOUSE_FILTERS
    return _from_mapping(payload)


def resolve_house_filters(
    request: Request,
    *,
    ort: str,
    radius_km: Decimal | None,
    preis_von: Decimal | None,
    preis_bis: Decimal | None,
    wohn_von: Decimal | None,
    wohn_bis: Decimal | None,
    nutz_von: Decimal | None,
    nutz_bis: Decimal | None,
    grund_von: Decimal | None,
    grund_bis: Decimal | None,
) -> HouseFilters:
    if request.query_params.get("filter_reset") == "1":
        return EMPTY_HOUSE_FILTERS

    explicitly_submitted = any(key in request.query_params for key in FILTER_QUERY_KEYS)
    if not explicitly_submitted:
        return load_house_filters(request)

    normalized_ort = ort.strip()[:120]
    return HouseFilters(
        ort=normalized_ort,
        radius_km=_safe_radius(radius_km, has_location=bool(normalized_ort)),
        preis_von=preis_von,
        preis_bis=preis_bis,
        wohn_von=wohn_von,
        wohn_bis=wohn_bis,
        nutz_von=nutz_von,
        nutz_bis=nutz_bis,
        grund_von=grund_von,
        grund_bis=grund_bis,
    )


def save_house_filters(response: Response, filters: HouseFilters) -> None:
    response.set_cookie(
        COOKIE_NAME,
        json.dumps(filters.as_cookie_payload(), separators=(",", ":")),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _distance_label(value: Decimal) -> str:
    if value == value.to_integral_value():
        return f"{value:,.0f}".replace(",", ".")
    return format(value, "f")


def house_filter_summary(filters: HouseFilters) -> str:
    parts: list[str] = []
    if filters.ort:
        location = filters.ort
        if filters.radius_km is not None:
            location += f" · Umkreis {_distance_label(filters.radius_km)} km"
        parts.append(location)
    if filters.preis_von is not None or filters.preis_bis is not None:
        if filters.preis_von is not None and filters.preis_bis is not None:
            parts.append(
                f"Preis {filters.preis_von:,.0f}–{filters.preis_bis:,.0f} €".replace(",", ".")
            )
        elif filters.preis_von is not None:
            parts.append(f"Preis ab {filters.preis_von:,.0f} €".replace(",", "."))
        else:
            parts.append(f"Preis bis {filters.preis_bis:,.0f} €".replace(",", "."))
    if filters.wohn_von is not None:
        parts.append(f"Wohnfläche ab {filters.wohn_von:,.0f} m²".replace(",", "."))
    if filters.wohn_bis is not None:
        parts.append(f"Wohnfläche bis {filters.wohn_bis:,.0f} m²".replace(",", "."))
    if filters.nutz_von is not None:
        parts.append(f"Nutzfläche ab {filters.nutz_von:,.0f} m²".replace(",", "."))
    if filters.nutz_bis is not None:
        parts.append(f"Nutzfläche bis {filters.nutz_bis:,.0f} m²".replace(",", "."))
    if filters.grund_von is not None:
        parts.append(f"Grundstück ab {filters.grund_von:,.0f} m²".replace(",", "."))
    if filters.grund_bis is not None:
        parts.append(f"Grundstück bis {filters.grund_bis:,.0f} m²".replace(",", "."))
    return " · ".join(parts) if parts else "Keine zusätzlichen Filter"
