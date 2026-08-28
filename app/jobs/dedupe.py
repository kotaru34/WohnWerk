from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

_GENDER_RE = re.compile(
    r"(?:\([^)]*(?:m\s*[/|]\s*w|w\s*[/|]\s*m|all genders)[^)]*\)|\ball genders\b)",
    re.IGNORECASE,
)
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(?:gmbh\s+und\s+co\s+kg|gmbh\s+co\s+kg|gesmbh|gmbh|mbh|ag|kg|og)\b"
)
_TITLE_FILLER = {"at", "bei"}


@dataclass(frozen=True, slots=True)
class DuplicateJobSnapshot:
    job_id: int
    title: str
    company: str | None
    postal_codes: frozenset[str]
    cities: frozenset[str]
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DuplicateEvidence:
    left_job_id: int
    right_job_id: int
    confidence: str
    title_similarity: float
    company_match: bool
    location_match: bool
    location_conflict: bool
    reasons: tuple[str, ...]


def _ascii_words(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.replace("&", " und ")
    return [word for word in _NON_WORD_RE.sub(" ", normalized).split() if word]


def normalize_job_title(value: str | None) -> str:
    cleaned = _GENDER_RE.sub(" ", value or "")
    words = [word for word in _ascii_words(cleaned) if word not in _TITLE_FILLER]
    return " ".join(words)


def normalize_company(value: str | None) -> str:
    words = _ascii_words(value)
    if not words:
        return ""
    normalized = " ".join(words)
    normalized = _COMPANY_SUFFIX_RE.sub(" ", normalized)
    return " ".join(normalized.split())


def normalize_locality(value: str | None) -> str:
    return " ".join(_ascii_words(value))


def title_similarity(left: str | None, right: str | None) -> float:
    left_normalized = normalize_job_title(left)
    right_normalized = normalize_job_title(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def duplicate_evidence(
    left: DuplicateJobSnapshot,
    right: DuplicateJobSnapshot,
) -> DuplicateEvidence | None:
    if left.job_id == right.job_id:
        return None

    left_company = normalize_company(left.company)
    right_company = normalize_company(right.company)
    company_match = bool(left_company and left_company == right_company)
    company_conflict = bool(left_company and right_company and left_company != right_company)
    if company_conflict:
        return None

    similarity = title_similarity(left.title, right.title)

    postal_match = bool(left.postal_codes & right.postal_codes)
    city_match = bool(left.cities & right.cities)
    location_match = postal_match or city_match

    postal_conflict = bool(
        left.postal_codes and right.postal_codes and not postal_match
    )
    city_conflict = bool(
        not left.postal_codes
        and not right.postal_codes
        and left.cities
        and right.cities
        and not city_match
    )
    location_conflict = postal_conflict or city_conflict

    reasons: list[str] = []
    if company_match:
        reasons.append("company_exact")
    if similarity == 1.0:
        reasons.append("title_normalized_exact")
    elif similarity >= 0.88:
        reasons.append(f"title_similarity={similarity:.3f}")
    if location_match:
        reasons.append("location_overlap")
    if location_conflict:
        reasons.append("location_conflict")

    high_confidence = (
        company_match and similarity >= 0.94 and location_match
    ) or (
        company_match and similarity == 1.0 and not location_conflict
    )
    medium_confidence = (
        company_match and similarity >= 0.88 and not location_conflict
    ) or (
        similarity == 1.0 and location_match and not location_conflict
    )

    if high_confidence:
        confidence = "high"
    elif medium_confidence:
        confidence = "medium"
    else:
        return None

    return DuplicateEvidence(
        left_job_id=left.job_id,
        right_job_id=right.job_id,
        confidence=confidence,
        title_similarity=similarity,
        company_match=company_match,
        location_match=location_match,
        location_conflict=location_conflict,
        reasons=tuple(reasons),
    )
