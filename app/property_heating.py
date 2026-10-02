from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser

HEATING_LABELS_DE: dict[str, str] = {
    "wood": "Holz",
    "pellet": "Pellets",
    "oil": "Öl",
    "electric": "Elektro",
    "gas": "Gas",
    "heat_pump": "Wärmepumpe",
    "district": "Fernwärme",
    "solar": "Solar",
    "biomass": "Biomasse",
    "coal": "Kohle",
}

WOOD_PREFERRED_TYPES = frozenset({"wood"})

_LABEL_RE = re.compile(
    r"(?:wesentlicher\s+energietr(?:ä|ae)ger|wesentliche\s+energietr(?:ä|ae)ger|"
    r"prim(?:ä|ae)renergietr(?:ä|ae)ger|energietr(?:ä|ae)ger|befeuerung|"
    r"heizungsart|heizung|w(?:ä|ae)rmeerzeuger)"
    r"\s*[:\-]?\s*(?:\|\s*)?(?P<value>[^|]{0,120})",
    re.IGNORECASE,
)

_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "wood",
        re.compile(
            r"\b(?:scheitholz|st(?:ü|ue)ckholz|holzheizung|holzvergaser|holzofen|holz)\b",
            re.IGNORECASE,
        ),
    ),
    ("pellet", re.compile(r"\bpellet(?:s|heizung|ofen)?\b", re.IGNORECASE)),
    (
        "oil",
        re.compile(
            r"\b(?:heiz(?:ö|oe)l|(?:ö|oe)lheizung|(?:ö|oe)lofen|(?:ö|oe)l)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "electric",
        re.compile(
            r"\b(?:elektroheizung|elektrisch\w*|strom|nachtspeicher(?:heizung|ofen)?)\b",
            re.IGNORECASE,
        ),
    ),
    ("gas", re.compile(r"\b(?:erdgas|gasheizung|gastherme|gas)\b", re.IGNORECASE)),
    (
        "heat_pump",
        re.compile(
            r"\b(?:w(?:ä|ae)rmepumpe|luftw(?:ä|ae)rmepumpe|erdw(?:ä|ae)rme)\b",
            re.IGNORECASE,
        ),
    ),
    ("district", re.compile(r"\bfernw(?:ä|ae)rme\b", re.IGNORECASE)),
    ("solar", re.compile(r"\b(?:solarthermie|solar)\b", re.IGNORECASE)),
    ("biomass", re.compile(r"\bbiomasse\b", re.IGNORECASE)),
    ("coal", re.compile(r"\b(?:kohle|kohleheizung)\b", re.IGNORECASE)),
)

_COMPOUND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "wood",
        re.compile(
            r"\b(?:holzheizung|holzvergaser|holzofen|scheitholzheizung|"
            r"st(?:ü|ue)ckholzheizung)\b",
            re.IGNORECASE,
        ),
    ),
    ("pellet", re.compile(r"\b(?:pelletheizung|pelletofen)\b", re.IGNORECASE)),
    ("oil", re.compile(r"\b(?:(?:ö|oe)lheizung|(?:ö|oe)lofen)\b", re.IGNORECASE)),
    (
        "electric",
        re.compile(r"\b(?:elektroheizung|nachtspeicher(?:heizung|ofen))\b", re.IGNORECASE),
    ),
    ("gas", re.compile(r"\b(?:gasheizung|gastherme)\b", re.IGNORECASE)),
    (
        "heat_pump",
        re.compile(r"\b(?:w(?:ä|ae)rmepumpe|luftw(?:ä|ae)rmepumpe)\b", re.IGNORECASE),
    ),
    ("district", re.compile(r"\bfernw(?:ä|ae)rme\b", re.IGNORECASE)),
    ("solar", re.compile(r"\bsolarthermie\b", re.IGNORECASE)),
    ("biomass", re.compile(r"\bbiomasseheizung\b", re.IGNORECASE)),
    ("coal", re.compile(r"\bkohleheizung\b", re.IGNORECASE)),
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "noscript"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        value = " ".join(data.split())
        if value:
            self.parts.append(value)

    def text(self) -> str:
        # Keep visible DOM text-node boundaries so a short evidence field can never
        # bleed into the following description/contact section after HTML flattening.
        return " | ".join(self.parts)


@dataclass(frozen=True, slots=True)
class HeatingEvidence:
    types: tuple[str, ...]
    evidence: tuple[str, ...]

    @property
    def wood_preferred(self) -> bool:
        return bool(WOOD_PREFERRED_TYPES.intersection(self.types))

    @property
    def labels_de(self) -> tuple[str, ...]:
        return tuple(
            HEATING_LABELS_DE[item]
            for item in self.types
            if item in HEATING_LABELS_DE
        )


def _types_in_text(value: str) -> set[str]:
    return {key for key, pattern in _VALUE_PATTERNS if pattern.search(value)}


def normalize_heating_types(values: Iterable[str]) -> tuple[str, ...]:
    known = {value for value in values if value in HEATING_LABELS_DE}
    return tuple(key for key in HEATING_LABELS_DE if key in known)


def extract_heating_evidence_from_text(text: str) -> HeatingEvidence:
    normalized = " ".join(text.split())
    if not normalized:
        return HeatingEvidence((), ())

    found: set[str] = set()
    evidence: list[str] = []

    for match in _LABEL_RE.finditer(normalized):
        value = (match.group("value") or "").strip()
        types = _types_in_text(value)
        if not types:
            continue
        found.update(types)
        snippet = " ".join(match.group(0).split())[:180]
        if snippet not in evidence:
            evidence.append(snippet)

    # Compound technology names are sufficiently specific without a nearby label.
    # Bare words such as Gas, Holz or Strom are deliberately label-scoped.
    for key, pattern in _COMPOUND_PATTERNS:
        direct = pattern.search(normalized)
        if direct is None:
            continue
        if key not in found:
            found.add(key)
            token = direct.group(0)
            if token not in evidence:
                evidence.append(token)

    return HeatingEvidence(normalize_heating_types(found), tuple(evidence[:8]))


def extract_heating_evidence_from_html(html: str) -> HeatingEvidence:
    parser = _VisibleTextParser()
    parser.feed(html)
    return extract_heating_evidence_from_text(parser.text())


def heating_evidence_from_payload(payload: dict | None) -> HeatingEvidence:
    value = payload or {}
    raw_types = value.get("heating_types")
    types = (
        normalize_heating_types(str(item) for item in raw_types)
        if isinstance(raw_types, list)
        else ()
    )
    raw_evidence = value.get("heating_evidence")
    evidence = (
        tuple(str(item) for item in raw_evidence if str(item).strip())[:8]
        if isinstance(raw_evidence, list)
        else ()
    )
    return HeatingEvidence(types, evidence)


def merge_heating_into_payload(payload: dict | None, evidence: HeatingEvidence) -> dict:
    result = dict(payload or {})
    if evidence.types:
        current = heating_evidence_from_payload(result)
        result["heating_types"] = list(
            normalize_heating_types((*current.types, *evidence.types))
        )
    if evidence.evidence:
        current_values = result.get("heating_evidence")
        merged = (
            [str(item) for item in current_values if str(item).strip()]
            if isinstance(current_values, list)
            else []
        )
        for item in evidence.evidence:
            if item not in merged:
                merged.append(item)
        result["heating_evidence"] = merged[:8]
    return result
