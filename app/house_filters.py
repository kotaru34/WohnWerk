from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from fastapi import Request, Response

COOKIE_NAME = "wohnwerk_house_filters_v1"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365
FILTER_QUERY_KEYS = frozenset(
    {
        "ort",
        "preis_von",
        "preis_bis",
        "wohn_von",
        "wohn_bis",
        "grund_von",
        "grund_bis",
    }
)


@dataclass(frozen=True, slots=True)
class HouseFilters:
    ort: str = ""
    preis_von: Decimal | None = Decimal("30000")
    preis_bis: Decimal | None = Decimal("150000")
    wohn_von: Decimal | None = Decimal("90")
    wohn_bis: Decimal | None = None
    grund_von: Decimal | None = Decimal("300")
    grund_bis: Decimal | None = None

    def as_cookie_payload(self) -> dict[str, str | None]:
        return {
            "ort": self.ort,
            "preis_von": _decimal_text(self.preis_von),
            "preis_bis": _decimal_text(self.preis_bis),
            "wohn_von": _decimal_text(self.wohn_von),
            "wohn_bis": _decimal_text(self.wohn_bis),
            "grund_von": _decimal_text(self.grund_von),
            "grund_bis": _decimal_text(self.grund_bis),
        }


BASE_HOUSE_FILTERS = HouseFilters()


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _safe_decimal(value: object) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _from_mapping(payload: dict[str, object]) -> HouseFilters:
    raw_ort = payload.get("ort")
    ort = raw_ort.strip()[:120] if isinstance(raw_ort, str) else ""
    return HouseFilters(
        ort=ort,
        preis_von=_safe_decimal(payload.get("preis_von")),
        preis_bis=_safe_decimal(payload.get("preis_bis")),
        wohn_von=_safe_decimal(payload.get("wohn_von")),
        wohn_bis=_safe_decimal(payload.get("wohn_bis")),
        grund_von=_safe_decimal(payload.get("grund_von")),
        grund_bis=_safe_decimal(payload.get("grund_bis")),
    )


def load_house_filters(request: Request) -> HouseFilters:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return BASE_HOUSE_FILTERS
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return BASE_HOUSE_FILTERS
    if not isinstance(payload, dict):
        return BASE_HOUSE_FILTERS
    return _from_mapping(payload)


def resolve_house_filters(
    request: Request,
    *,
    ort: str,
    preis_von: Decimal | None,
    preis_bis: Decimal | None,
    wohn_von: Decimal | None,
    wohn_bis: Decimal | None,
    grund_von: Decimal | None,
    grund_bis: Decimal | None,
) -> HouseFilters:
    if request.query_params.get("filter_reset") == "1":
        return BASE_HOUSE_FILTERS

    explicitly_submitted = any(key in request.query_params for key in FILTER_QUERY_KEYS)
    if not explicitly_submitted:
        return load_house_filters(request)

    return HouseFilters(
        ort=ort.strip()[:120],
        preis_von=preis_von,
        preis_bis=preis_bis,
        wohn_von=wohn_von,
        wohn_bis=wohn_bis,
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


def house_filter_summary(filters: HouseFilters) -> str:
    parts: list[str] = []
    if filters.ort:
        parts.append(filters.ort)
    if filters.preis_von is not None or filters.preis_bis is not None:
        if filters.preis_von is not None and filters.preis_bis is not None:
            parts.append(f"Preis {filters.preis_von:,.0f}–{filters.preis_bis:,.0f} €".replace(",", "."))
        elif filters.preis_von is not None:
            parts.append(f"Preis ab {filters.preis_von:,.0f} €".replace(",", "."))
        else:
            parts.append(f"Preis bis {filters.preis_bis:,.0f} €".replace(",", "."))
    if filters.wohn_von is not None:
        parts.append(f"Wohnfläche ab {filters.wohn_von:,.0f} m²".replace(",", "."))
    if filters.wohn_bis is not None:
        parts.append(f"Wohnfläche bis {filters.wohn_bis:,.0f} m²".replace(",", "."))
    if filters.grund_von is not None:
        parts.append(f"Grundstück ab {filters.grund_von:,.0f} m²".replace(",", "."))
    if filters.grund_bis is not None:
        parts.append(f"Grundstück bis {filters.grund_bis:,.0f} m²".replace(",", "."))
    return " · ".join(parts) if parts else "Kein zusätzlicher Hausfilter"
