from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

_IMMOSCOUT_HOSTS = {
    "immobilienscout24.at",
    "www.immobilienscout24.at",
    "immobilienscout24.de",
    "www.immobilienscout24.de",
}


@dataclass(frozen=True, slots=True)
class ImmoScoutPropertyFacts:
    purchase_price_eur: Decimal | None = None
    living_area_m2: Decimal | None = None
    usable_area_m2: Decimal | None = None
    plot_area_m2: Decimal | None = None
    postal_code: str | None = None
    object_number: str | None = None
    title: str | None = None


def _json_scalar(text: str, key: str) -> str | None:
    match = re.search(
        rf'"{re.escape(key)}"\s*:\s*'
        rf'(?:"(?P<quoted>[^"\\]*(?:\\.[^"\\]*)*)"|'
        rf'(?P<bare>-?\d+(?:\.\d+)?|null))',
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    value = (
        match.group("quoted")
        if match.group("quoted") is not None
        else match.group("bare")
    )
    if value is None or value.casefold() == "null":
        return None
    return value.replace(r"\u0026", "&").replace(r"\/", "/")


def _typed_json_object(text: str, key: str, typename: str) -> str | None:
    match = re.search(
        rf'"{re.escape(key)}"\s*:\s*\{{\s*'
        rf'"__typename"\s*:\s*"{re.escape(typename)}"',
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None

    start = text.find("{", match.start())
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    normalized = value.strip().replace(" ", "")
    if "," in normalized and "." not in normalized:
        normalized = normalized.replace(",", ".")
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None


def _first_decimal(text: str, keys: tuple[str, ...]) -> Decimal | None:
    for key in keys:
        value = _decimal(_json_scalar(text, key))
        if value is not None:
            return value
    return None


def extract_immoscout_property_facts(
    url: str,
    body: str,
) -> ImmoScoutPropertyFacts | None:
    """Extract authoritative listing facts from ImmoScout embedded page metadata."""
    host = (urlparse(url).hostname or "").casefold()
    if host not in _IMMOSCOUT_HOSTS:
        return None

    purchase_price = _first_decimal(body, ("obj_purchasePrice",))
    living_area = _first_decimal(body, ("obj_livingSpace", "obj_livingArea"))
    usable_area = _first_decimal(body, ("obj_usableArea", "obj_useableArea"))
    plot_area = _first_decimal(body, ("obj_lotArea", "obj_plotArea", "obj_landArea"))

    area_object = _typed_json_object(body, "area", "Area")
    if area_object is not None:
        if living_area is None:
            living_area = _first_decimal(area_object, ("livingArea",))
        if usable_area is None:
            usable_area = _first_decimal(area_object, ("effectiveArea",))
        if plot_area is None:
            plot_area = _first_decimal(area_object, ("plotArea",))

    postal_code = _json_scalar(body, "obj_zipCode")
    object_number = _json_scalar(body, "obj_objectnumber")
    title = _json_scalar(body, "obj_title")

    if not any(
        (
            purchase_price,
            living_area,
            usable_area,
            plot_area,
            postal_code,
            object_number,
            title,
        )
    ):
        return None
    return ImmoScoutPropertyFacts(
        purchase_price_eur=purchase_price,
        living_area_m2=living_area,
        usable_area_m2=usable_area,
        plot_area_m2=plot_area,
        postal_code=postal_code.strip() if postal_code else None,
        object_number=object_number.strip() if object_number else None,
        title=title.strip() if title else None,
    )


def _normalize_title(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9äöüß]+", value.casefold()))


def immoscout_facts_match_listing(
    facts: ImmoScoutPropertyFacts,
    *,
    listing_url: str,
    postal_code: str | None,
    title: str | None,
) -> bool:
    """Require strong identity evidence before provider detail facts enrich a row."""
    path_token = urlparse(listing_url).path.rstrip("/").split("/")[-1]
    object_match = bool(facts.object_number and path_token == facts.object_number)

    if facts.object_number and path_token and not object_match:
        return False
    if facts.postal_code and postal_code and facts.postal_code != postal_code:
        return False

    title_match = False
    if facts.title and title:
        source_title = _normalize_title(facts.title)
        stored_title = _normalize_title(title)
        if source_title and stored_title:
            title_match = source_title in stored_title or stored_title in source_title
            if not title_match:
                source_tokens = set(source_title.split())
                stored_tokens = set(stored_title.split())
                overlap = len(source_tokens & stored_tokens)
                denominator = max(1, min(len(source_tokens), len(stored_tokens)))
                title_match = overlap >= 3 and overlap / denominator >= 0.6
        if not title_match and not object_match:
            return False

    if object_match:
        return True
    return bool(
        facts.postal_code
        and postal_code
        and facts.postal_code == postal_code
        and facts.title
        and title
        and title_match
    )
