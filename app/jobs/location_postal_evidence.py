from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_WS_RE = re.compile(r"\s+")


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        value = _WS_RE.sub(" ", data).strip()
        if value:
            self.parts.append(value)


def visible_page_text(content: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(content)
    return html.unescape(" ".join(parser.parts))


def explicit_postal_for_locality(content: str, locality: str | None) -> str | None:
    """Return a unique Austrian PLZ explicitly printed next to a source locality.

    This is evidence extraction, not geocoding: WohnWerk only accepts a four-digit postal
    code when the same source page prints it immediately before the exact locality label,
    e.g. ``4085 Niederranna`` or ``A-4085 Niederranna``. If the page contains conflicting
    PLZ values for that locality, fail closed rather than choosing one.
    """
    raw_locality = " ".join((locality or "").split()).strip()
    if not raw_locality:
        return None

    locality_pattern = re.escape(raw_locality).replace(r"\ ", r"\s+")
    pattern = re.compile(
        rf"(?<!\d)(?:A\s*[-–—]?\s*)?(?P<postal>\d{{4}})\s+{locality_pattern}(?=\b|\s|[,.;:/()])",
        re.IGNORECASE,
    )
    matches = {match.group("postal") for match in pattern.finditer(visible_page_text(content))}
    if len(matches) != 1:
        return None
    return next(iter(matches))
