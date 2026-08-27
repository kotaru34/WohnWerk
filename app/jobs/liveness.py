from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

_SPACE_RE = re.compile(r"\s+")

_CLOSED_PAGE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "no_longer_available",
        re.compile(
            r"\b(?:this\s+)?(?:job|position|role)\s+(?:is\s+)?no\s+longer\s+available\b"
        ),
    ),
    (
        "no_longer_accepting_applications",
        re.compile(
            r"\b(?:this\s+)?(?:job|position|role)\s+(?:is\s+)?no\s+longer\s+"
            r"accepting\s+applications\b"
        ),
    ),
    (
        "applications_closed",
        re.compile(r"\bapplications?\s+(?:are|is|have\s+been)\s+closed\b"),
    ),
    (
        "job_expired",
        re.compile(r"\b(?:this\s+)?(?:job|position|role)\s+(?:has\s+)?expired\b"),
    ),
    (
        "application_period_ended",
        re.compile(r"\bapplication\s+(?:period|window)\s+(?:has\s+)?ended\b"),
    ),
    (
        "stelle_nicht_mehr_verfuegbar",
        re.compile(
            r"\b(?:diese\s+)?(?:stelle|position|stellenanzeige|stellenangebot)\s+ist\s+"
            r"nicht\s+mehr\s+verf(?:ü|ue)gbar\b"
        ),
    ),
    (
        "bewerbung_nicht_mehr_moeglich",
        re.compile(
            r"\bbewerb(?:ung|ungen)\w*[^.]{0,80}\bnicht\s+mehr\s+m(?:ö|oe)glich\b"
        ),
    ),
    (
        "bewerbungsfrist_abgelaufen",
        re.compile(r"\bbewerbungsfrist\w*[^.]{0,40}\babgelaufen\b"),
    ),
)


@dataclass(frozen=True, slots=True)
class PageLivenessAssessment:
    state: str
    reasons: tuple[str, ...] = ()


def normalize_page_text(value: str | None) -> str:
    if not value:
        return ""
    return _SPACE_RE.sub(" ", value.casefold()).strip()


def closed_page_markers(value: str | None) -> tuple[str, ...]:
    text = normalize_page_text(value)
    if not text:
        return ()
    return tuple(name for name, pattern in _CLOSED_PAGE_PATTERNS if pattern.search(text))


def assess_http_page(status_code: int | None, body: str | None) -> PageLivenessAssessment:
    """Classify HTTP evidence without treating anti-bot/transient errors as closure."""
    if status_code is None:
        return PageLivenessAssessment("unknown", ("request_failed",))
    if status_code in {404, 410}:
        return PageLivenessAssessment("dead", (f"http_{status_code}",))

    markers = closed_page_markers(body)
    if markers:
        return PageLivenessAssessment("dead", markers)

    if 200 <= status_code < 400:
        return PageLivenessAssessment("live")
    if status_code in {401, 403, 429} or status_code >= 500:
        return PageLivenessAssessment("unknown", (f"http_{status_code}",))
    return PageLivenessAssessment("unknown", (f"http_{status_code}",))


def parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def released_age_days(value: object, *, now: datetime | None = None) -> int | None:
    released = parse_iso_datetime(value)
    if released is None:
        return None
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    delta = current.astimezone(UTC) - released
    return max(0, delta.days)
