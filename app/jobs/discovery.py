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

DISCOVERY_GATE_VERSION = "profile-seed-2026-08-30-v19"

_OPERATIONAL_TEST_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "vehicle_test_operator",
        re.compile(
            r"\b(?:autonomous\s+)?vehicle\s+test\s+operator\w*"
            r"|\bav\s+test\s+operator\w*"
        ),
    ),
)

_ADJACENT_TITLE_AUGMENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "service_technician",
        re.compile(
            r"\b(?:field[-\s]+service[-\s]+technician|service\s+technician|"
            r"servicetechniker|service\s+techniker)\w*"
        ),
    ),
    ("field_service_manager", re.compile(r"\bfield[-\s]+service[-\s]+manager\w*")),
    (
        "production_lead",
        re.compile(
            r"\b(?:produktionsleiter|fertigungsleiter|production\s+manager|"
            r"manufacturing\s+manager)\w*"
        ),
    ),
    ("team_lead", re.compile(r"\bteamleitung\w*")),
)

_DOMAIN_AUGMENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "building_services",
        re.compile(
            r"\b(?:gebäudetechnik|gebaeudetechnik|hkls|tga|hvac|"
            r"building\s+(?:services?|systems?))\w*"
        ),
    ),
    ("manufacturing_compound", re.compile(r"\b\w*fertigung\w*")),
)

_STRUCTURAL_STAGE_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "student_training_stage",
        re.compile(
            r"\b(?:(?:doppel)?lehre|lehrstelle|lehrausbildung)\w*"
            r"|\b(?:working\s+student|student\s+(?:employee|worker))\w*"
        ),
    ),
    (
        "graduate_entry_stage",
        re.compile(
            r"\b(?:absolvent\w*|graduate\w*|berufseinsteiger\w*|"
            r"career\s+starter\w*|entry[-\s]*level\w*)"
        ),
    ),
    ("junior_stage", re.compile(r"\bjunior\b")),
    (
        "academic_thesis",
        re.compile(
            r"\b(?:bachelor(?:'s)?[-/\s]*(?:master)?arbeit|bachelorarbeit|masterarbeit|"
            r"bachelor(?:'s)?\s+thesis|master(?:'s)?\s+thesis)\b"
        ),
    ),
    (
        "unsolicited_application",
        re.compile(
            r"\b(?:initiativbewerbung|unsolicited\s+application|"
            r"speculative\s+application)\w*"
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
    (
        "vehicle_workshop_trade",
        re.compile(
            r"\b(?:kfz[-\s]*(?:mechatroniker|techniker)|"
            r"automotive\s+(?:mechanic|technician))\w*"
        ),
    ),
    (
        "cnc_turning_milling_trade",
        re.compile(
            r"\bcnc[-\s]*(?:dreher|fräser|fraeser)\w*"
            r"(?:\s*/?\s*-\s*(?:dreher|fräser|fraeser)\w*)?"
            r"|\bcnc\s+(?:turner|miller|machinist)\w*"
            r"|\bcnc[-\s]*(?:turning|milling)\s+(?:operator|machinist)\w*"
        ),
    ),
    (
        "laboratory_technician",
        re.compile(r"\b(?:labortechniker|laboratory\s+technician|lab\s+technician)\w*"),
    ),
)

_BUSINESS_OPERATION_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "procurement_commercial",
        re.compile(
            r"\b(?:procurement|purchas(?:er|ing)|buyer|einkäufer\w*|einkauf\w*)\b"
        ),
    ),
    ("logistics_operations", re.compile(r"\b(?:logistics?|logistik)\w*")),
    ("expansion_management", re.compile(r"\bexpansion\s+(?:project\s+)?manager\w*")),
    (
        "production_operator",
        re.compile(
            r"\b(?:cutting\s+machine|machining|cnc)\s+operator\w*"
            r"|\b(?:maschinen|anlagen)bediener\w*"
        ),
    ),
    (
        "packaging_planning",
        re.compile(r"\b(?:verpackungsplaner|packaging\s+(?:planner|planning))\w*"),
    ),
)

_NON_TARGET_PROFESSIONAL_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "qa_ra_regulatory",
        re.compile(
            r"\b(?:qa\s*/\s*ra|quality\s+assurance\s*/\s*regulatory\s+affairs|"
            r"regulatory\s+affairs)\b"
        ),
    ),
    ("solution_delivery_engineer", re.compile(r"\bsolution\s+delivery\s+engineer\b")),
    (
        "building_physics",
        re.compile(
            r"\b(?:bauphysik(?:er|erin)?|ingenieur\s+für\s+bauphysik|"
            r"building\s+physics(?:\s+engineer)?)\b"
        ),
    ),
    (
        "fire_safety_engineer",
        re.compile(
            r"\b(?:fire\s+safety\s+engineer|brandschutz(?:ingenieur|techniker))\w*"
        ),
    ),
    (
        "building_cost_optimization",
        re.compile(
            r"\bcost\s+optimi[sz]ation\b.*\bbuilding\s+systems?\b"
            r"|\bbuilding\s+systems?\b.*\bcost\s+optimi[sz]ation\b"
        ),
    ),
    ("r_and_d_operations_manager", re.compile(r"\br\s*[&/]\s*d\s+operations\s+manager\b")),
    (
        "it_program_project_role",
        re.compile(
            r"\b(?:program\s*/\s*project\s+responsible|project\s+responsible)\s+it\b"
            r"|\bit\s+(?:program|project)\s+(?:responsible|manager|lead)\b"
        ),
    ),
)

_ELECTRICAL_ENGINEERING_TITLE_RE = re.compile(
    r"\b(?:electrical\s+engineer|elektroingenieur)\w*"
)
_ELECTRICAL_ADJACENT_DOMAINS = frozenset(
    {
        "maschinenbau",
        "mechanical",
        "vehicle_engineering",
        "special_vehicle",
        "rail_vehicle",
        "autonomous_vehicle_systems",
        "vehicle_electronics",
        "fixture_tooling",
        "plant_engineering",
        "special_machinery",
        # Generic manufacturing/fertigung language is intentionally not enough to
        # rescue an electrical-engineering title. Employer boilerplate frequently
        # contains those words even when the vacancy itself is pure electrical /
        # automation work (for example EPLAN/control-cabinet roles).
        "product_development",
        "component_development",
        "chassis_structure",
        "wheel_development",
    }
)

_AFTER_SALES_SERVICE_RE = re.compile(r"\bafter[-\s]+sales(?:\s+service)?\b")

_HARD_TITLE_EXCLUSIONS = frozenset(
    {
        "student_training_stage",
        "graduate_entry_stage",
        "academic_thesis",
        "unsolicited_application",
        "software_role",
        "ai_data_role",
        "vehicle_workshop_trade",
    }
)

_BLOCKING_NEGATIVE_TITLE_CONTEXTS = frozenset(
    {
        "software",
        "generic_it",
        "data_ai",
        "enterprise_it",
    }
)


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.casefold().split())


def _discovery_extra_text(job: RawJob) -> str:
    value = (job.raw_payload or {}).get("wohnwerk_discovery_extra_text")
    if isinstance(value, str):
        return _normalize(value)
    if isinstance(value, list):
        return "\n".join(_normalize(item) for item in value if isinstance(item, str))
    return ""


def _negative_context_text(text: str) -> str:
    """Protect technical after-sales service from generic commercial sales matching."""
    return _AFTER_SALES_SERVICE_RE.sub("after_sales_service", text)


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
    extra = _discovery_extra_text(job)
    combined = f"{title}\n{body}\n{extra}"

    strong_title = _matches(STRONG_TITLE_PATTERNS, title)
    adjacent_role = tuple(
        dict.fromkeys(
            (
                *_matches(ADJACENT_ROLE_PATTERNS, title),
                *_matches(_ADJACENT_TITLE_AUGMENT_PATTERNS, title),
            )
        )
    )
    low_relevance_title = tuple(
        dict.fromkeys(
            (
                *_matches(LOW_RELEVANCE_TITLE_PATTERNS, title),
                *_matches(_OPERATIONAL_TEST_TITLE_PATTERNS, title),
                *_matches(_STRUCTURAL_STAGE_TITLE_PATTERNS, title),
                *_matches(_MANUAL_TRADE_TITLE_PATTERNS, title),
                *_matches(_BUSINESS_OPERATION_TITLE_PATTERNS, title),
                *_matches(_NON_TARGET_PROFESSIONAL_TITLE_PATTERNS, title),
            )
        )
    )
    domain = tuple(
        dict.fromkeys(
            (
                *_matches(DOMAIN_PATTERNS, combined),
                *_matches(_DOMAIN_AUGMENT_PATTERNS, combined),
            )
        )
    )
    method_tool = _matches(METHOD_TOOL_PATTERNS, combined)
    negative_text = _negative_context_text(combined)
    negative = _matches(NEGATIVE_CONTEXT_PATTERNS, negative_text)
    negative_title = set(
        _matches(NEGATIVE_CONTEXT_PATTERNS, _negative_context_text(title))
    )

    blocking_negative = tuple(
        name for name in negative if name != "hr" or name in negative_title
    )

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

    if _ELECTRICAL_ENGINEERING_TITLE_RE.search(title) and not set(domain).intersection(
        _ELECTRICAL_ADJACENT_DOMAINS
    ):
        electrical_low_relevance = tuple(
            dict.fromkeys((*low_relevance_title, "non_mechanical_electrical_engineering"))
        )
        return _decision(
            accepted=False,
            reason="insufficient_base_relevance",
            strong_title=strong_title,
            adjacent_role=adjacent_role,
            domain=domain,
            method_tool=method_tool,
            negative=negative,
            low_relevance_title=electrical_low_relevance,
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

    if negative_title.intersection(_BLOCKING_NEGATIVE_TITLE_CONTEXTS):
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

    domain_count = len(set(domain))
    method_count = len(set(method_tool))
    has_role = bool(adjacent_role)
    has_negative = bool(blocking_negative)

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