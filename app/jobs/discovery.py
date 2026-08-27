from __future__ import annotations

import re
from dataclasses import dataclass

from app.jobs.profile_seed import (
    ADJACENT_ROLE_PATTERNS,
    DOMAIN_PATTERNS,
    LOW_RELEVANCE_TITLE_PATTERNS,
    METHOD_TOOL_PATTERNS,
    NEGATIVE_CONTEXT_PATTERNS,
    STRONG_TITLE_PATTERNS,
)
from app.sources.base import RawJob

DISCOVERY_GATE_VERSION = "profile-seed-2026-08-27-v9"

_OPERATIONAL_TEST_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "vehicle_test_operator",
        re.compile(
            r"\b(?:autonomous\s+)?vehicle\s+test\s+operator\w*"
            r"|\bav\s+test\s+operator\w*"
        ),
    ),
)

_STRUCTURAL_STAGE_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "student_training_stage",
        re.compile(r"\b(?:(?:doppel)?lehre|lehrstelle|lehrausbildung)\w*"),
    ),
    (
        "graduate_entry_stage",
        re.compile(
            r"\b(?:absolvent\w*|graduate\w*|berufseinsteiger\w*|"
            r"career\s+starter\w*|entry[-\s]*level\w*)"
        ),
    ),
)

_MANUAL_TRADE_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "manual_metal_trade",
        re.compile(
            r"\b(?:metallfacharbeiter|facharbeiter|schlosser|mechaniker|"
            r"schweißer|schweisser|welder)\w*"
        ),
    ),
)

_BUSINESS_OPERATION_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "procurement_commercial",
        re.compile(
            r"\b(?:procurement|purchas(?:er|ing)|buyer|einkäufer\w*|einkauf\w*)\b"
        ),
    ),
    (
        "logistics_operations",
        re.compile(r"\b(?:logistics?|logistik)\w*"),
    ),
    (
        "expansion_management",
        re.compile(r"\bexpansion\s+(?:project\s+)?manager\w*"),
    ),
    (
        "production_operator",
        re.compile(
            r"\b(?:cutting\s+machine|machining|cnc)\s+operator\w*"
            r"|\b(?:maschinen|anlagen)bediener\w*"
        ),
    ),
)

# These title semantics are structural exclusions for this experienced
# working-professional corpus and therefore win even over an otherwise strong
# mechanical title.
_HARD_TITLE_EXCLUSIONS = frozenset(
    {
        "student_training_stage",
        "graduate_entry_stage",
        "software_role",
        "ai_data_role",
    }
)


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.casefold().split())


@dataclass(frozen=True, slots=True)
class JobDiscoveryDecision:
    accepted: bool
    reason: str
    strong_title_matches: tuple[str, ...] = ()
    adjacent_title_matches: tuple[str, ...] = ()
    support_matches: tuple[str, ...] = ()
    domain_matches: tuple[str, ...] = ()
    method_tool_matches: tuple[str, ...] = ()
    negative_context_matches: tuple[str, ...] = ()
    low_relevance_title_matches: tuple[str, ...] = ()


def _matches(
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    text: str,
) -> tuple[str, ...]:
    return tuple(name for name, pattern in patterns if pattern.search(text))


def _decision(
    *,
    accepted: bool,
    reason: str,
    strong_title: tuple[str, ...],
    adjacent_role: tuple[str, ...],
    domain: tuple[str, ...],
    method_tool: tuple[str, ...],
    negative: tuple[str, ...],
    low_relevance_title: tuple[str, ...],
) -> JobDiscoveryDecision:
    return JobDiscoveryDecision(
        accepted=accepted,
        reason=reason,
        strong_title_matches=strong_title,
        adjacent_title_matches=adjacent_role,
        support_matches=tuple(dict.fromkeys((*domain, *method_tool))),
        domain_matches=domain,
        method_tool_matches=method_tool,
        negative_context_matches=negative,
        low_relevance_title_matches=low_relevance_title,
    )


def classify_job_candidate(job: RawJob) -> JobDiscoveryDecision:
    """Apply a high-recall professional-neighbourhood gate before persistence."""
    title = _normalize(job.title)
    body = _normalize(job.description)
    combined = f"{title}\n{body}"

    strong_title = _matches(STRONG_TITLE_PATTERNS, title)
    adjacent_role = _matches(ADJACENT_ROLE_PATTERNS, title)
    low_relevance_title = tuple(
        dict.fromkeys(
            (
                *_matches(LOW_RELEVANCE_TITLE_PATTERNS, title),
                *_matches(_OPERATIONAL_TEST_TITLE_PATTERNS, title),
                *_matches(_STRUCTURAL_STAGE_TITLE_PATTERNS, title),
                *_matches(_MANUAL_TRADE_TITLE_PATTERNS, title),
                *_matches(_BUSINESS_OPERATION_TITLE_PATTERNS, title),
            )
        )
    )
    domain = _matches(DOMAIN_PATTERNS, combined)
    method_tool = _matches(METHOD_TOOL_PATTERNS, combined)
    negative = _matches(NEGATIVE_CONTEXT_PATTERNS, combined)

    if any(match in _HARD_TITLE_EXCLUSIONS for match in low_relevance_title):
        return _decision(
            accepted=False,
            reason="structural_title_exclusion",
            strong_title=strong_title,
            adjacent_role=adjacent_role,
            domain=domain,
            method_tool=method_tool,
            negative=negative,
            low_relevance_title=low_relevance_title,
        )

    if strong_title:
        return _decision(
            accepted=True,
            reason="strong_mechanical_title",
            strong_title=strong_title,
            adjacent_role=adjacent_role,
            domain=domain,
            method_tool=method_tool,
            negative=negative,
            low_relevance_title=low_relevance_title,
        )

    if low_relevance_title:
        return _decision(
            accepted=False,
            reason="low_relevance_operational_title",
            strong_title=strong_title,
            adjacent_role=adjacent_role,
            domain=domain,
            method_tool=method_tool,
            negative=negative,
            low_relevance_title=low_relevance_title,
        )

    domain_count = len(set(domain))
    method_count = len(set(method_tool))
    has_role = bool(adjacent_role)
    has_negative = bool(negative)

    if has_role and domain_count >= 1 and (not has_negative or method_count >= 1):
        return _decision(
            accepted=True,
            reason="engineering_role_with_domain",
            strong_title=strong_title,
            adjacent_role=adjacent_role,
            domain=domain,
            method_tool=method_tool,
            negative=negative,
            low_relevance_title=low_relevance_title,
        )

    if has_role and method_count >= 1 and not has_negative:
        return _decision(
            accepted=True,
            reason="engineering_role_with_method",
            strong_title=strong_title,
            adjacent_role=adjacent_role,
            domain=domain,
            method_tool=method_tool,
            negative=negative,
            low_relevance_title=low_relevance_title,
        )

    if domain_count >= 2 and method_count >= 1:
        return _decision(
            accepted=True,
            reason="multiple_domains_with_method",
            strong_title=strong_title,
            adjacent_role=adjacent_role,
            domain=domain,
            method_tool=method_tool,
            negative=negative,
            low_relevance_title=low_relevance_title,
        )

    if method_count >= 3 and not has_negative:
        return _decision(
            accepted=True,
            reason="multiple_engineering_methods",
            strong_title=strong_title,
            adjacent_role=adjacent_role,
            domain=domain,
            method_tool=method_tool,
            negative=negative,
            low_relevance_title=low_relevance_title,
        )

    return _decision(
        accepted=False,
        reason="insufficient_base_relevance",
        strong_title=strong_title,
        adjacent_role=adjacent_role,
        domain=domain,
        method_tool=method_tool,
        negative=negative,
        low_relevance_title=low_relevance_title,
    )


def _attach_discovery_evidence(item: RawJob, decision: JobDiscoveryDecision) -> None:
    payload = dict(item.raw_payload)
    payload["wohnwerk_discovery_gate"] = {
        "version": DISCOVERY_GATE_VERSION,
        "accepted": decision.accepted,
        "reason": decision.reason,
        "strong_title_matches": list(decision.strong_title_matches),
        "adjacent_title_matches": list(decision.adjacent_title_matches),
        "support_matches": list(decision.support_matches),
        "domain_matches": list(decision.domain_matches),
        "method_tool_matches": list(decision.method_tool_matches),
        "negative_context_matches": list(decision.negative_context_matches),
        "low_relevance_title_matches": list(decision.low_relevance_title_matches),
    }
    item.raw_payload = payload


def partition_job_candidates(items: list[RawJob]) -> tuple[list[RawJob], list[RawJob]]:
    """Classify all Austrian source candidates while preserving evidence for both sides."""
    accepted: list[RawJob] = []
    rejected: list[RawJob] = []

    for item in items:
        decision = classify_job_candidate(item)
        _attach_discovery_evidence(item, decision)
        if decision.accepted:
            accepted.append(item)
        else:
            rejected.append(item)

    return accepted, rejected


def filter_job_candidates(items: list[RawJob]) -> list[RawJob]:
    """Backward-compatible accepted-only helper."""
    accepted: list[RawJob] = []
    for item in items:
        decision = classify_job_candidate(item)
        if not decision.accepted:
            continue
        _attach_discovery_evidence(item, decision)
        accepted.append(item)
    return accepted
