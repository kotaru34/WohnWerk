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

_OPERATIONAL_TEST_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "vehicle_test_operator",
        re.compile(
            r"\b(?:autonomous\s+)?vehicle\s+test\s+operator\w*"
            r"|\bav\s+test\s+operator\w*"
        ),
    ),
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
    """Apply a high-recall professional-neighbourhood gate before persistence.

    The gate is deliberately broader than a CV title list. It recognizes strong
    mechanical titles directly and otherwise combines role-family, engineering-
    domain, and method/tool evidence. Obvious IT/commercial context only dampens
    weak matches; clearly operational title families can be rejected before weak
    body-text signals accidentally promote them.
    """
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
            )
        )
    )
    domain = _matches(DOMAIN_PATTERNS, combined)
    method_tool = _matches(METHOD_TOOL_PATTERNS, combined)
    negative = _matches(NEGATIVE_CONTEXT_PATTERNS, combined)

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

    # A plausible engineering role plus a real mechanical/manufacturing domain is
    # normally enough. If the vacancy is strongly software/commercial, require an
    # additional mechanical method/tool signal rather than trusting one word such
    # as "automotive".
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

    # CAD/FEM/FMEA/PLM/etc. can reveal a relevant adjacent role even when the
    # source uses an unusual title. One method/tool signal is sufficient when the
    # title itself is already an engineering/technical role and the context is not
    # clearly unrelated.
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

    # Generic or novel titles remain discoverable when the body contains multiple
    # independent mechanical domains plus a concrete engineering method/tool.
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

    # A method-heavy vacancy can still be relevant despite a weak title. This is
    # useful for titles such as "Technical Specialist" or supplier-side roles.
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


def filter_job_candidates(items: list[RawJob]) -> list[RawJob]:
    accepted: list[RawJob] = []
    for item in items:
        decision = classify_job_candidate(item)
        if not decision.accepted:
            continue

        payload = dict(item.raw_payload)
        payload["wohnwerk_discovery_gate"] = {
            "accepted": True,
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
        accepted.append(item)
    return accepted
