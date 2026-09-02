from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

_IMMOSCOUT_HOSTS = {
    "immobilienscout24.at",
    "www.immobilienscout24.at",
    "immobilienscout24.de",
    "www.immobilienscout24.de",
}
_FINDMYHOME_HOSTS = {"findmyhome.at", "www.findmyhome.at"}
_SUPPORTED_DETAIL_HOSTS = _IMMOSCOUT_HOSTS | _FINDMYHOME_HOSTS
_IMAGE_META_KEYS = {"og:image", "twitter:image", "twitter:image:src"}


@dataclass(frozen=True, slots=True)
class ImmoScoutPropertyFacts:
    """Provider-backed property facts used by the conservative detail worker.

    The historical class name is retained because it is imported by existing callers and
    scripts. The same neutral shape is now also used for explicitly supported downstream
    providers such as FindMyHome.
    """

    purchase_price_eur: Decimal | None = None
    living_area_m2: Decimal | None = None
    usable_area_m2: Decimal | None = None
    plot_area_m2: Decimal | None = None
    postal_code: str | None = None
    object_number: str | None = None
    title: str | None = None
    primary_image_url: str | None = None


PropertyDetailFacts = ImmoScoutPropertyFacts


class _DocumentParser(HTMLParser):
    def __init__(self, *, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.visible_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.primary_image_url: str | None = None
        self._hidden_depth = 0
        self._h1_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag == "meta" and self.primary_image_url is None:
            key = (attributes.get("property") or attributes.get("name") or "").casefold()
            content = attributes.get("content", "").strip()
            if key in _IMAGE_META_KEYS and content:
                self.primary_image_url = _safe_absolute_http_url(content, base_url=self.page_url)

        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1
            return
        if self._hidden_depth:
            return
        if tag == "h1":
            self._h1_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "meta":
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)
            return
        if self._hidden_depth:
            return
        if tag == "h1":
            self._h1_depth = max(0, self._h1_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        self.visible_parts.append(cleaned)
        if self._h1_depth:
            self.h1_parts.append(cleaned)

    @property
    def visible_text(self) -> str:
        return " ".join(self.visible_parts)

    @property
    def h1(self) -> str | None:
        value = " ".join(self.h1_parts).strip()
        return value or None


def _safe_absolute_http_url(value: str | None, *, base_url: str) -> str | None:
    if not value:
        return None
    absolute = urljoin(base_url, value.strip())
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return absolute


def _document(body: str, *, page_url: str) -> _DocumentParser:
    parser = _DocumentParser(page_url=page_url)
    parser.feed(body)
    return parser


def supported_property_detail_url(value: object | None) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and (parsed.hostname or "").casefold() in _SUPPORTED_DETAIL_HOSTS
    )


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
    normalized = value.strip().replace("\xa0", "").replace(" ", "")
    normalized = re.sub(r"[^0-9,.-]", "", normalized)
    if not normalized:
        return None
    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif "," in normalized:
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
    parsed_document = _document(body, page_url=url)

    if not any(
        (
            purchase_price,
            living_area,
            usable_area,
            plot_area,
            postal_code,
            object_number,
            title,
            parsed_document.primary_image_url,
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
        primary_image_url=parsed_document.primary_image_url,
    )


def _localized_number_pattern() -> str:
    return r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?"


def extract_findmyhome_property_facts(
    url: str,
    body: str,
) -> PropertyDetailFacts | None:
    """Extract FindMyHome house facts from explicit visible labels.

    FindMyHome labels its house-card summary simply as ``Fläche``. For the provider's
    ``Immobilienart: Haus - Eigentum`` pages that summary is the residential house area,
    while ``Grundfläche`` is separately labelled. We only apply this mapping under that
    exact provider/type context instead of guessing generic m² values.
    """
    parsed_url = urlparse(url)
    host = (parsed_url.hostname or "").casefold()
    if host not in _FINDMYHOME_HOSTS:
        return None

    object_number = parsed_url.path.rstrip("/").split("/")[-1]
    if not object_number.isdigit():
        return None

    parsed_document = _document(body, page_url=url)
    visible = parsed_document.visible_text
    normalized_visible = " ".join(visible.casefold().split())
    if not re.search(r"\bimmobilienart\s+haus\s*-\s*eigentum\b", normalized_visible):
        return None

    number = _localized_number_pattern()
    living_match = re.search(
        rf"(?P<value>{number})\s*m(?:²|2)\s+Fläche\b",
        visible,
        re.IGNORECASE,
    )
    plot_match = re.search(
        rf"\bGrundfläche\s+(?P<value>{number})\s*m(?:²|2)\b",
        visible,
        re.IGNORECASE,
    )
    price_match = re.search(
        rf"€\s*(?P<value>{number})\s+Kaufpreis\b",
        visible,
        re.IGNORECASE,
    ) or re.search(
        rf"\bKaufpreis\s*:?\s*€\s*(?P<value>{number})\b",
        visible,
        re.IGNORECASE,
    )
    postal_match = re.search(r"\bAnschrift\s+(?P<postal>\d{4})\b", visible, re.IGNORECASE)

    title = parsed_document.h1
    if title:
        title = re.sub(
            rf"\s*-\s*Objektnr\.\s*{re.escape(object_number)}\s*$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()

    return PropertyDetailFacts(
        purchase_price_eur=_decimal(price_match.group("value")) if price_match else None,
        living_area_m2=_decimal(living_match.group("value")) if living_match else None,
        plot_area_m2=_decimal(plot_match.group("value")) if plot_match else None,
        postal_code=postal_match.group("postal") if postal_match else None,
        object_number=object_number,
        title=title,
        primary_image_url=parsed_document.primary_image_url,
    )


def extract_property_detail_facts(url: str, body: str) -> PropertyDetailFacts | None:
    host = (urlparse(url).hostname or "").casefold()
    if host in _IMMOSCOUT_HOSTS:
        return extract_immoscout_property_facts(url, body)
    if host in _FINDMYHOME_HOSTS:
        return extract_findmyhome_property_facts(url, body)
    return None


def _normalize_title(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9äöüß]+", value.casefold()))


def property_facts_match_listing(
    facts: PropertyDetailFacts,
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


def immoscout_facts_match_listing(
    facts: ImmoScoutPropertyFacts,
    *,
    listing_url: str,
    postal_code: str | None,
    title: str | None,
) -> bool:
    """Backward-compatible wrapper for existing tests and callers."""
    return property_facts_match_listing(
        facts,
        listing_url=listing_url,
        postal_code=postal_code,
        title=title,
    )
