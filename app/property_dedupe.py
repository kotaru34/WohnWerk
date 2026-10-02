from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from app.models import Property

_NON_WORD_RE = re.compile(r"[^a-z0-9]+")
_GENERIC_TITLE_TOKENS = frozenset(
    {
        "haus",
        "kaufen",
        "verkauf",
        "einfamilienhaus",
        "zweifamilienhaus",
        "mehrfamilienhaus",
        "immobilie",
        "objekt",
        "familienhaus",
        "mit",
        "und",
        "in",
        "im",
        "der",
        "die",
        "das",
        "ein",
        "eine",
        "zum",
        "zur",
    }
)


@dataclass(frozen=True, slots=True)
class PropertyDuplicateKey:
    postal_code: str
    price_eur: Decimal
    normalized_title: str


def normalize_property_title(value: str | None) -> str:
    """Normalize only typography, never semantics, for duplicate matching."""
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
    """Return a deliberately narrow exact identity key for syndicated adverts.

    Both Austrian four-digit and German five-digit postal codes are supported. The
    key still requires exact cent-level price and a substantial normalized title;
    short/generic titles remain excluded.
    """
    postal = (postal_code or "").strip()
    if not re.fullmatch(r"\d{4,5}", postal) or price_eur is None:
        return None
    normalized_title = normalize_property_title(title)
    if len(normalized_title) < 28 or len(normalized_title.split()) < 5:
        return None
    try:
        price = Decimal(price_eur).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return PropertyDuplicateKey(postal, price, normalized_title)


def _numeric_compatible(
    left: Decimal | None,
    right: Decimal | None,
    *,
    absolute: Decimal,
    relative: Decimal,
) -> bool | None:
    if left is None or right is None:
        return None
    tolerance = max(absolute, max(abs(left), abs(right)) * relative)
    return abs(left - right) <= tolerance


def _areas_compatible(left: Decimal | None, right: Decimal | None) -> bool:
    compatible = _numeric_compatible(
        left,
        right,
        absolute=Decimal(1),
        relative=Decimal("0.01"),
    )
    return compatible is not False


def _title_tokens(value: str | None) -> set[str]:
    return {
        token
        for token in normalize_property_title(value).split()
        if len(token) >= 3 and token not in _GENERIC_TITLE_TOKENS
    }


def _title_similarity(left: str | None, right: str | None) -> float:
    left_normalized = normalize_property_title(left)
    right_normalized = normalize_property_title(right)
    if not left_normalized or not right_normalized:
        return 0.0
    sequence = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    union = left_tokens | right_tokens
    token_score = len(left_tokens & right_tokens) / len(union) if union else 0.0
    return max(sequence, token_score)


def cross_source_duplicate_strategy(
    candidate: Property,
    *,
    postal_code: str | None,
    price_eur: Decimal | None,
    title: str | None,
    living_area_m2: Decimal | None,
    plot_area_m2: Decimal | None,
) -> str | None:
    """Return a conservative cross-source match strategy or None.

    A German/Austrian PLZ and compatible asking price are mandatory. Explicit
    contradictory areas veto a match. Unlike the legacy exact-title key, this can
    recognize a syndicated advert whose portal rewrites the headline, but only when
    source-independent numeric facts provide enough corroboration.
    """
    postal = (postal_code or "").strip()
    if not re.fullmatch(r"\d{4,5}", postal) or candidate.postal_code != postal:
        return None

    price_match = _numeric_compatible(
        candidate.price_eur,
        price_eur,
        absolute=Decimal(500),
        relative=Decimal("0.005"),
    )
    if price_match is not True:
        return None

    living_match = _numeric_compatible(
        candidate.living_area_m2,
        living_area_m2,
        absolute=Decimal(3),
        relative=Decimal("0.02"),
    )
    plot_match = _numeric_compatible(
        candidate.plot_area_m2,
        plot_area_m2,
        absolute=Decimal(15),
        relative=Decimal("0.02"),
    )
    if living_match is False or plot_match is False:
        return None

    exact_left = property_duplicate_key(
        postal_code=candidate.postal_code,
        price_eur=candidate.price_eur,
        title=candidate.title,
    )
    exact_right = property_duplicate_key(
        postal_code=postal_code,
        price_eur=price_eur,
        title=title,
    )
    if exact_left is not None and exact_left == exact_right:
        return "exact_postal_price_title"

    similarity = _title_similarity(candidate.title, title)
    explicit_area_matches = sum(value is True for value in (living_match, plot_match))

    if explicit_area_matches == 2 and similarity >= 0.35:
        return "postal_price_living_plot_title"
    if explicit_area_matches >= 1 and similarity >= 0.78:
        return "postal_price_area_title"
    return None


def properties_have_compatible_duplicate_facts(left: Property, right: Property) -> bool:
    """Reject an exact title/price/PLZ match when explicit canonical areas conflict."""
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
