from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.models import Property

_NON_WORD_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class PropertyDuplicateKey:
    postal_code: str
    price_eur: Decimal
    normalized_title: str


def normalize_property_title(value: str | None) -> str:
    """Normalize only typography, never semantics, for high-confidence duplicate matching."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.replace("ß", "ss")
    return " ".join(_NON_WORD_RE.sub(" ", normalized).split())


def property_duplicate_key(
    *,
    postal_code: str | None,
    price_eur: Decimal | None,
    title: str | None,
) -> PropertyDuplicateKey | None:
    """Return a deliberately narrow identity key for syndicated house adverts.

    The key requires the same Austrian PLZ, exact cent-level price and a substantial title
    equal after punctuation/Unicode normalization. Short/generic titles are excluded so a
    common label such as ``Einfamilienhaus`` can never merge unrelated properties.
    """
    postal = (postal_code or "").strip()
    if not re.fullmatch(r"\d{4}", postal) or price_eur is None:
        return None
    normalized_title = normalize_property_title(title)
    if len(normalized_title) < 28 or len(normalized_title.split()) < 5:
        return None
    try:
        price = Decimal(price_eur).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return PropertyDuplicateKey(postal, price, normalized_title)


def _areas_compatible(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return True
    tolerance = max(Decimal(1), max(abs(left), abs(right)) * Decimal("0.01"))
    return abs(left - right) <= tolerance


def properties_have_compatible_duplicate_facts(left: Property, right: Property) -> bool:
    """Reject a title/price/PLZ match when explicit canonical areas contradict it."""
    left_key = property_duplicate_key(
        postal_code=left.postal_code,
        price_eur=left.price_eur,
        title=left.title,
    )
    right_key = property_duplicate_key(
        postal_code=right.postal_code,
        price_eur=right.price_eur,
        title=right.title,
    )
    if left_key is None or left_key != right_key:
        return False
    return _areas_compatible(
        left.living_area_m2,
        right.living_area_m2,
    ) and _areas_compatible(
        left.plot_area_m2,
        right.plot_area_m2,
    )
