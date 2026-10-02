from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PropertySourceBrand:
    key: str
    label: str
    color: str
    icon_text: str


_BRANDS: dict[str, PropertySourceBrand] = {
    "sreal.at": PropertySourceBrand("sreal", "s REAL", "#e2001a", "s"),
    "immmo.at": PropertySourceBrand("immmo", "IMMMO", "#e36f1e", "IM"),
    "immowelt-de": PropertySourceBrand("immowelt", "immowelt", "#f26a21", "iw"),
    "kleinanzeigen-de": PropertySourceBrand(
        "kleinanzeigen", "Kleinanzeigen", "#00a878", "K"
    ),
    "engel-voelkers-de": PropertySourceBrand(
        "engel-voelkers", "Engel & Völkers", "#8b1f2d", "E&V"
    ),
    "immoscout24-de": PropertySourceBrand(
        "immoscout24", "ImmoScout24", "#ff7500", "24"
    ),
    "von-poll-de": PropertySourceBrand("von-poll", "VON POLL", "#21384f", "VP"),
    "willhaben.at": PropertySourceBrand("willhaben", "willhaben", "#c6168d", "w"),
}

_FALLBACK = PropertySourceBrand("source", "Quelle", "#6f7782", "↗")


def property_source_brand(source_name: str | None) -> PropertySourceBrand:
    normalized = str(source_name or "").strip().casefold()
    brand = _BRANDS.get(normalized)
    if brand is not None:
        return brand
    if not normalized:
        return _FALLBACK

    label = str(source_name).strip()
    icon = "".join(part[:1] for part in label.replace("-", " ").split()[:2]).upper()
    if not icon:
        icon = _FALLBACK.icon_text
    return PropertySourceBrand("source", label, _FALLBACK.color, icon[:3])
