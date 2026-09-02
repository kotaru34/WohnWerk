from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from app.jobs.salary import ParsedSalary, parse_salary_text

_DETAIL_WORTHY_RE = re.compile(
    r"(?:konstruk|maschinenbau|mechanical|cad|entwicklungsingenieur|"
    r"development\s+engineer|design\s+engineer|project\s+engineer|projektingenieur|"
    r"technisch\w*\s+projekt|projektleiter|sondermaschinen|fahrzeug|automotive|"
    r"berechnungsingenieur|simulation\s+engineer|product\s+engineer|"
    r"mechanik|baugruppen|antrieb|chassis)",
    re.IGNORECASE,
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "noscript", "template", "svg"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "template", "svg"}:
            self.hidden_depth = max(0, self.hidden_depth - 1)

    def handle_data(self, data: str) -> None:
        if self.hidden_depth:
            return
        cleaned = " ".join(html.unescape(data).split()).strip()
        if cleaned:
            self.parts.append(cleaned)


def detail_worthy_title(title: str) -> bool:
    return bool(_DETAIL_WORTHY_RE.search(title))


def visible_detail_text(content: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(content)
    return "\n".join(parser.parts)


def parse_salary_detail_html(content: str) -> ParsedSalary | None:
    """Parse only explicit salary language from visible detail-page text."""
    return parse_salary_text(visible_detail_text(content))
