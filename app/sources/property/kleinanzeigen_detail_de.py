"""Fail-closed parsing of public Kleinanzeigen DE house detail facts.

Parsing only: no network, no seller contacts, no arbitrary HTML persistence.
Scheduled detail fetching remains opt-in until provider terms are validated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit

from app.property_heating import HeatingEvidence, extract_heating_evidence_from_text

_DETAIL_PATH = re.compile(r"^/s-anzeige/[^/]+/(?P<id>\d{8,12})-208-\d+/?$")
_LISTING_ID = re.compile(r"\bAnzeigen-ID\s*\|?\s*(\d{8,12})\b", re.IGNORECASE)
_PLOT_LABEL = re.compile(
    r"^(?:Grundst(?:ü|ue)cksfl(?:ä|ae)che|"
    r"Grundst(?:ü|ue)cksgr(?:ö|oe)(?:ß|ss)e)\s*:?\s*",
    re.IGNORECASE,
)
_PLOT_VALUE = re.compile(
    r"^(?:ca\.?\s*|circa\s*)?"
    r"(?P<number>\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d{1,5}(?:[,.]\d{1,2})?)"
    r"\s*(?:m²|m2|qm)(?!\w)",
    re.IGNORECASE,
)
_END_MARKERS = frozenset({
    "Nachricht schreiben", "Andere Anzeigen des Anbieters",
    "Ähnliche Anzeigen", "Rechtliche Angaben",
})


class _VisibleFields(HTMLParser):
    """Keep DOM text boundaries so labels only match local values."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


@dataclass(frozen=True, slots=True)
class KleinanzeigenHouseFacts:
    listing_id: str
    plot_area_m2: Decimal | None
    heating: HeatingEvidence
    plot_evidence: str | None


def _area(value: str) -> Decimal | None:
    match = _PLOT_VALUE.match(value)
    if match is None:
        return None
    number = match.group("number")
    if "," in number:
        number = number.replace(".", "").replace(",", ".")
    elif "." in number and len(number.rsplit(".", 1)[-1]) == 3:
        number = number.replace(".", "")
    try:
        parsed = Decimal(number)
    except InvalidOperation:
        return None
    return parsed if Decimal("10") <= parsed <= Decimal("100000") else None


def _plot_candidates(parts: list[str]) -> list[tuple[Decimal, str]]:
    candidates: list[tuple[Decimal, str]] = []
    for i, part in enumerate(parts):
        label = _PLOT_LABEL.match(part)
        if label is None:
            continue
        remaining = part[label.end():].strip()
        # HTML often puts a label in one <dt> and its value in the next <dd>.
        if not remaining and i + 1 < len(parts):
            remaining = parts[i + 1].strip()
        number = _area(remaining)
        if number is not None:
            candidates.append((number, f"{part[:65]} {remaining[:40]}".strip()[:110]))
    return candidates


def parse_kleinanzeigen_house_detail(
    html: str,
    *,
    url: str,
    expected_listing_id: str,
) -> KleinanzeigenHouseFacts:
    """Reject mismatched ad identities; refuse ambiguous plot measurements.

    No data from seller sections or recommended listings is used as evidence.
    """
    uri = urlsplit(url)
    match = _DETAIL_PATH.fullmatch(uri.path)
    if (
        uri.scheme != "https"
        or uri.hostname not in {"www.kleinanzeigen.de", "kleinanzeigen.de"}
        or uri.port is not None
        or uri.username is not None
        or match is None
        or match.group("id") != expected_listing_id
    ):
        raise ValueError("untrusted detail URL or mismatched house listing ID")

    parser = _VisibleFields()
    parser.feed(html)
    joined = " | ".join(parser.parts)
    ids = _LISTING_ID.findall(joined)
    if not ids or ids[0] != expected_listing_id:
        raise ValueError("detail page does not visibly identify the requested advert")

    parts: list[str] = []
    for part in parser.parts:
        if any(marker.casefold() == part.casefold() for marker in _END_MARKERS):
            break
        parts.append(part)
    if not parts or any(part.strip().casefold() == "gelöscht" for part in parts[:50]):
        raise ValueError("deleted or unrecognized house detail")

    plots = _plot_candidates(parts)
    distinct = {value for value, _evidence in plots}
    plot = next(iter(distinct)) if len(distinct) == 1 else None
    provenance = next((evidence for value, evidence in plots if value == plot), None)
    heating = extract_heating_evidence_from_text(" | ".join(parts))
    return KleinanzeigenHouseFacts(expected_listing_id, plot, heating, provenance)
