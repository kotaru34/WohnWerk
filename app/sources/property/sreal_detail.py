from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from app.sources.base import RawProperty
from app.sources.property.immmo import _clean_text, _decimal

DETAIL_PATH_RE = re.compile(r"^/de/immobilie/(?P<listing_id>[^/]+)/", re.IGNORECASE)
AREA_VALUE = r"(?P<value>[\d.]+(?:,\d+)?)"
AREA_PREFIX = r"(?:ca\.?\s*|rund\s+|knapp\s+|etwa\s+)?"
AREA_UNIT = r"\s*m\s*(?:²|2)\b"
LIVING_LABEL = r"(?:Wohnfläche|Wohnnutzfläche|Wohn[\s/-]*Nutzfläche)"
USABLE_LABEL = r"Nutzfläche"
PLOT_LABEL = r"(?:Grundfläche|Grundstücksfläche|Grundstück)"


def _area_patterns(label: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    return (
        re.compile(
            rf"\b{label}\s*(?::|von)?\s*{AREA_PREFIX}{AREA_VALUE}{AREA_UNIT}",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b{AREA_PREFIX}{AREA_VALUE}{AREA_UNIT}\s+{label}\b(?!\s*:)",
            re.IGNORECASE,
        ),
    )


LIVING_AREA_PATTERNS = _area_patterns(LIVING_LABEL)
USABLE_AREA_PATTERNS = _area_patterns(USABLE_LABEL)
PLOT_AREA_PATTERNS = _area_patterns(PLOT_LABEL)
PRICE_RE = re.compile(
    r"\bKaufpreis\s+(?P<value>[\d.]+(?:,\d+)?)\s*€",
    re.IGNORECASE,
)
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5"}
IMAGE_META_KEYS = {"og:image", "twitter:image", "twitter:image:src"}


@dataclass(frozen=True, slots=True)
class _Heading:
    text: str
    start: int
    end: int


@dataclass(slots=True)
class _HeadingFrame:
    tag: str
    start: int
    parts: list[str] = field(default_factory=list)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._length = 0
        self._hidden_depth = 0
        self._heading_stack: list[_HeadingFrame] = []
        self.headings: list[_Heading] = []
        self.primary_image_url: str | None = None

    @property
    def text(self) -> str:
        return "".join(self._chunks)

    def _append(self, value: str) -> None:
        cleaned = _clean_text(value)
        if not cleaned:
            return
        prefix = " " if self._length else ""
        self._chunks.append(prefix + cleaned)
        self._length += len(prefix) + len(cleaned)
        if self._heading_stack:
            self._heading_stack[-1].parts.append(cleaned)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1
            return
        if self._hidden_depth:
            return

        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag == "meta" and self.primary_image_url is None:
            meta_key = (attributes.get("property") or attributes.get("name") or "").casefold()
            content = attributes.get("content", "").strip()
            if meta_key in IMAGE_META_KEYS and content:
                self.primary_image_url = content
        elif tag == "link" and self.primary_image_url is None:
            rel = attributes.get("rel", "").casefold()
            href = attributes.get("href", "").strip()
            if "image_src" in rel.split() and href:
                self.primary_image_url = href

        if tag in HEADING_TAGS:
            self._heading_stack.append(_HeadingFrame(tag=tag, start=self._length))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)
            return
        if self._hidden_depth or tag not in HEADING_TAGS:
            return
        for index in range(len(self._heading_stack) - 1, -1, -1):
            if self._heading_stack[index].tag != tag:
                continue
            frame = self._heading_stack.pop(index)
            self.headings.append(
                _Heading(
                    text=_clean_text(" ".join(frame.parts)),
                    start=frame.start,
                    end=self._length,
                )
            )
            break

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self._append(data)


@dataclass(frozen=True, slots=True)
class SRealDetail:
    listing_id: str
    postal_code: str | None
    city: str | None
    price_eur: Decimal | None
    living_area_m2: Decimal | None
    usable_area_m2: Decimal | None
    plot_area_m2: Decimal | None
    description: str | None
    primary_image_url: str | None


def _listing_id(page_url: str) -> str:
    parsed = urlparse(page_url)
    match = DETAIL_PATH_RE.match(parsed.path)
    if match is None:
        raise ValueError(f"Not an s REAL detail URL: {page_url!r}")
    return match.group("listing_id")


def _description(parser: _VisibleTextParser) -> str | None:
    headings = sorted(parser.headings, key=lambda item: item.start)
    for index, heading in enumerate(headings):
        if heading.text.casefold() != "objektbeschreibung":
            continue
        end = headings[index + 1].start if index + 1 < len(headings) else len(parser.text)
        value = _clean_text(parser.text[heading.end:end])
        return value or None
    return None


def _primary_image(parser: _VisibleTextParser, *, page_url: str) -> str | None:
    if not parser.primary_image_url:
        return None
    absolute = urljoin(page_url, parser.primary_image_url)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return absolute


def _area_value(text: str, patterns: tuple[re.Pattern[str], re.Pattern[str]]) -> Decimal | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match is not None:
            return _decimal(match.group("value"))
    return None


def parse_sreal_detail_page(html: str, *, page_url: str) -> SRealDetail:
    parser = _VisibleTextParser()
    parser.feed(html)
    text = parser.text
    listing_id = _listing_id(page_url)

    display_id = listing_id.replace("-", "/", 1)
    location_re = re.compile(
        rf"\b(?P<plz>\d{{4}})\s+(?P<city>.{{1,100}}?)\s*-\s*{re.escape(display_id)}\b",
        re.IGNORECASE,
    )
    location = location_re.search(text)
    description = _description(parser)

    # Prefer a semantically explicit Wohn-/Wohnnutzfläche anywhere on the detail page,
    # including value-before-label prose such as "ca. 140 m² Wohnfläche". Generic
    # Nutzfläche is retained separately and is never silently renamed to Wohnfläche.
    living_area = _area_value(text, LIVING_AREA_PATTERNS)
    usable_area = _area_value(text, USABLE_AREA_PATTERNS)
    plot_area = _area_value(text, PLOT_AREA_PATTERNS)
    price = PRICE_RE.search(text)

    return SRealDetail(
        listing_id=listing_id,
        postal_code=location.group("plz") if location else None,
        city=_clean_text(location.group("city")).strip(" ,") if location else None,
        price_eur=_decimal(price.group("value")) if price else None,
        living_area_m2=living_area,
        usable_area_m2=usable_area,
        plot_area_m2=plot_area,
        description=description,
        primary_image_url=_primary_image(parser, page_url=page_url),
    )


def enrich_sreal_property(item: RawProperty, detail: SRealDetail) -> RawProperty:
    if item.source_listing_id != detail.listing_id:
        raise ValueError(
            f"s REAL detail ID mismatch: card={item.source_listing_id!r} detail={detail.listing_id!r}"
        )

    payload = dict(item.raw_payload)
    payload.update(
        {
            "detail_enriched": True,
            "detail_price_eur": str(detail.price_eur) if detail.price_eur is not None else None,
            "detail_living_area_m2": (
                str(detail.living_area_m2) if detail.living_area_m2 is not None else None
            ),
            "detail_usable_area_m2": (
                str(detail.usable_area_m2) if detail.usable_area_m2 is not None else None
            ),
            "detail_plot_area_m2": (
                str(detail.plot_area_m2) if detail.plot_area_m2 is not None else None
            ),
            "detail_area_semantics": {
                "living": "explicit_wohn_or_wohnnutzflaeche"
                if detail.living_area_m2 is not None
                else None,
                "usable": "explicit_nutzflaeche" if detail.usable_area_m2 is not None else None,
                "plot": "explicit_grund_or_grundstuecksflaeche"
                if detail.plot_area_m2 is not None
                else None,
            },
            "primary_image_url": detail.primary_image_url,
        }
    )

    return RawProperty(
        source_listing_id=item.source_listing_id,
        url=item.url,
        title=item.title,
        description=detail.description or item.description,
        price_eur=detail.price_eur if detail.price_eur is not None else item.price_eur,
        living_area_m2=(
            detail.living_area_m2
            if detail.living_area_m2 is not None
            else item.living_area_m2
        ),
        plot_area_m2=detail.plot_area_m2 if detail.plot_area_m2 is not None else item.plot_area_m2,
        postal_code=detail.postal_code or item.postal_code,
        city=detail.city or item.city,
        raw_payload=payload,
    )
