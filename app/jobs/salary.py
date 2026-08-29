from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.sources.base import RawJob

SALARY_TEXT_POLICY = "explicit-salary-text-2026-08-29-v1"

_AMOUNT_TOKEN = r"(?:\d{1,3}(?:[.\s\u00a0]\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_MONEY_RE = re.compile(
    rf"(?:\bEUR\s*(?P<prefix>{_AMOUNT_TOKEN})|€\s*(?P<euro_prefix>{_AMOUNT_TOKEN})|"
    rf"(?P<suffix>{_AMOUNT_TOKEN})\s*(?:€|\bEUR\b))",
    re.IGNORECASE,
)
_SALARY_CUE_RE = re.compile(
    r"(?:gehalt|mindestentgelt|entgelt|vergütung|verguetung|bezahlung|lohn|"
    r"\bbrutto\b|\bgross\b|salary|compensation|remuneration)",
    re.IGNORECASE,
)
_MINIMUM_RE = re.compile(
    r"(?:\bab\b|\bmindestens\b|\bmindest(?:gehalt|entgelt|lohn)?\b|"
    r"\bminimum\b|\bstarting\s+(?:at|from)\b|\bfrom\b)",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(r"(?:\bbis\b|\bto\b|\bbis\s+zu\b|\s[-–—]\s)", re.IGNORECASE)
_PAYMENT_14_RE = re.compile(
    r"(?:\b14\s*(?:x|mal)\b|\b14\s*(?:monats)?gehälter(?:n)?\b|"
    r"\b14\s*(?:monats)?gehaelter(?:n)?\b|\b14\s*(?:bezüge|bezuege|zahlungen)\b)",
    re.IGNORECASE,
)
_PERIOD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "month",
        re.compile(
            r"(?:\b(?:brutto)?monats(?:gehalt|entgelt|brutto)?\b|"
            r"\bmonatsbrutto(?:gehalt|entgelt)?\b|\bmonatlich\b|/\s*monat\b|"
            r"\bpro\s+monat\b|\bper\s+month\b|\bmonthly\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "year",
        re.compile(
            r"(?:\b(?:brutto)?jahres(?:brutto)?(?:gehalt|entgelt)?\b|"
            r"\bjahresbrutto(?:gehalt|entgelt)?\b|\bjährlich\b|\bjaehrlich\b|"
            r"/\s*jahr\b|\bpro\s+jahr\b|\bp\.?\s*a\.?\b|\bper\s+year\b|"
            r"\bannual(?:ly)?\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "hour",
        re.compile(
            r"(?:\bstunde(?:nlohn)?\b|/\s*stunde\b|\bpro\s+stunde\b|"
            r"\bper\s+hour\b|\bhourly\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "week",
        re.compile(
            r"(?:\bwoche\b|/\s*woche\b|\bpro\s+woche\b|\bper\s+week\b)",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class ParsedSalary:
    minimum: Decimal
    maximum: Decimal | None
    currency: str
    period: str
    payment_count: int | None
    minimum_only: bool
    text: str
    confidence: Decimal = Decimal("0.950")


def _decimal_amount(raw: str) -> Decimal | None:
    text = raw.replace("\u00a0", "").replace(" ", "").strip()
    if not text:
        return None

    if "," in text and "." in text:
        # German/Austrian notation: 4.673,74. If the final dot follows the comma,
        # accept the inverse English notation as well.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        tail = text.rsplit(",", 1)[1]
        text = text.replace(",", "") if len(tail) == 3 else text.replace(",", ".")
    elif "." in text:
        parts = text.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            text = "".join(parts)

    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _money_value(match: re.Match[str]) -> Decimal | None:
    raw = match.group("prefix") or match.group("euro_prefix") or match.group("suffix")
    return _decimal_amount(raw)


def _period(window: str) -> str | None:
    for period, pattern in _PERIOD_PATTERNS:
        if pattern.search(window):
            return period
    return None


def _plausible(value: Decimal, period: str) -> bool:
    if period == "month":
        return Decimal(800) <= value <= Decimal(30000)
    if period == "year":
        return Decimal(10000) <= value <= Decimal(500000)
    if period == "hour":
        return Decimal(5) <= value <= Decimal(500)
    if period == "week":
        return Decimal(200) <= value <= Decimal(15000)
    return False


def _snippet(text: str, start: int, end: int) -> str:
    left = text.rfind("\n", 0, start)
    right = text.find("\n", end)
    left = max(0, left + 1)
    right = len(text) if right < 0 else right
    line = " ".join(text[left:right].split())
    if len(line) < 12:
        line = " ".join(text[max(0, start - 100) : min(len(text), end + 140)].split())
    return line[:320]


def parse_salary_text(text: str | None) -> ParsedSalary | None:
    """Extract only explicit source salary statements with a stated pay period.

    Generic EUR amounts are deliberately ignored. A candidate must have a nearby salary
    cue and an explicit month/year/hour/week semantic, which keeps travel budgets, bonuses,
    revenue figures and other monetary values out of canonical salary fields.
    """
    if not text:
        return None

    matches = list(_MONEY_RE.finditer(text))
    for index, match in enumerate(matches):
        value = _money_value(match)
        if value is None:
            continue

        window_start = max(0, match.start() - 150)
        window_end = min(len(text), match.end() + 180)
        window = text[window_start:window_end]
        if _SALARY_CUE_RE.search(window) is None:
            continue
        period = _period(window)
        if period is None or not _plausible(value, period):
            continue

        # If this amount is the second half of an already-detectable range, let the
        # preceding amount own the range instead of producing a duplicate candidate.
        if index > 0:
            previous = matches[index - 1]
            between = text[previous.end() : match.start()]
            if len(between) <= 80 and _RANGE_RE.search(between):
                previous_value = _money_value(previous)
                previous_window = text[
                    max(0, previous.start() - 150) : min(len(text), match.end() + 120)
                ]
                if (
                    previous_value is not None
                    and _SALARY_CUE_RE.search(previous_window)
                    and _period(previous_window) == period
                    and _plausible(previous_value, period)
                ):
                    continue

        maximum: Decimal | None = None
        range_end = match.end()
        if index + 1 < len(matches):
            following = matches[index + 1]
            between = text[match.end() : following.start()]
            if len(between) <= 80 and _RANGE_RE.search(between):
                following_value = _money_value(following)
                combined = text[window_start : min(len(text), following.end() + 100)]
                if (
                    following_value is not None
                    and _period(combined) == period
                    and _plausible(following_value, period)
                ):
                    maximum = following_value
                    range_end = following.end()

        if maximum is not None and maximum < value:
            value, maximum = maximum, value

        broader = text[max(0, match.start() - 220) : min(len(text), range_end + 220)]
        minimum_only = maximum is None and _MINIMUM_RE.search(broader) is not None
        payment_count = 14 if period == "month" and _PAYMENT_14_RE.search(broader) else None
        return ParsedSalary(
            minimum=value,
            maximum=maximum,
            currency="EUR",
            period=period,
            payment_count=payment_count,
            minimum_only=minimum_only,
            text=_snippet(text, match.start(), range_end),
        )

    return None


def enrich_raw_job_salary(item: RawJob) -> bool:
    """Fill missing salary fields from explicit salary text without overriding structured data."""
    # Fully structured source data always wins.
    if (
        item.salary_min is not None
        and item.salary_currency is not None
        and item.salary_period is not None
    ):
        return False

    parsed = parse_salary_text(item.salary_text) or parse_salary_text(item.description)
    if parsed is None:
        return False

    if item.salary_min is not None and item.salary_min != parsed.minimum:
        return False
    if item.salary_max is not None and parsed.maximum is not None and item.salary_max != parsed.maximum:
        return False

    if item.salary_min is None:
        item.salary_min = parsed.minimum
    if item.salary_max is None:
        item.salary_max = parsed.maximum
    if item.salary_currency is None:
        item.salary_currency = parsed.currency
    if item.salary_period is None:
        item.salary_period = parsed.period
    if item.salary_payment_count is None:
        item.salary_payment_count = parsed.payment_count
    if item.salary_provenance is None:
        item.salary_provenance = "TEXT_EXPLICIT"
    if item.salary_confidence is None:
        item.salary_confidence = parsed.confidence
    if item.salary_is_minimum_only is None:
        item.salary_is_minimum_only = parsed.minimum_only
    if item.salary_text is None:
        item.salary_text = parsed.text

    payload = dict(item.raw_payload)
    payload["wohnwerk_salary_text_policy"] = SALARY_TEXT_POLICY
    payload["wohnwerk_salary_text"] = parsed.text
    item.raw_payload = payload
    return True


def enrich_raw_job_salaries(items: list[RawJob]) -> int:
    return sum(enrich_raw_job_salary(item) for item in items)
