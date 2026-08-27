from __future__ import annotations

from dataclasses import dataclass
import re

from app.sources.base import RawJob


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.casefold().split())


STRONG_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("maschinenbau", re.compile(r"\bmaschinenbau\w*")),
    ("konstruktion", re.compile(r"\bkonstrukt\w*")),
    ("entwicklungsingenieur", re.compile(r"\bentwicklungsingenieur\w*")),
    ("mechanical_engineer", re.compile(r"\bmechanical\s+(?:design\s+)?engineer\w*")),
    ("berechnungsingenieur", re.compile(r"\bberechnungsingenieur\w*")),
    ("cad_konstrukteur", re.compile(r"\bcad[-\s]*konstrukt\w*")),
    ("produktentwicklung", re.compile(r"\bproduktentwick\w*")),
    ("sondermaschinenbau", re.compile(r"\bsondermaschinenbau\w*")),
    ("mechatronik", re.compile(r"\bmechatronik\w*")),
)

ADJACENT_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("application_engineer", re.compile(r"\bapplication\s+engineer\w*")),
    ("project_engineer", re.compile(r"\bproject\s+engineer\w*")),
    ("projektingenieur", re.compile(r"\bprojektingenieur\w*")),
    ("projektleiter", re.compile(r"\bprojektleiter\w*")),
    ("product_engineer", re.compile(r"\bproduct\s+engineer\w*")),
    ("development_engineer", re.compile(r"\bdevelopment\s+engineer\w*")),
    ("design_engineer", re.compile(r"\bdesign\s+engineer\w*")),
    ("simulation_engineer", re.compile(r"\bsimulation\s+engineer\w*")),
    ("r_and_d_engineer", re.compile(r"\br\s*[&/]\s*d\s+engineer\w*")),
    ("technical_project", re.compile(r"\btechn(?:ical|isch\w*)\s+projekt\w*")),
)

SUPPORT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cad", re.compile(r"\bcad\b")),
    ("creo", re.compile(r"\bcreo\b")),
    ("solidworks", re.compile(r"\bsolidworks\b")),
    ("catia", re.compile(r"\bcatia\b")),
    ("inventor", re.compile(r"\bautodesk\s+inventor\b|\binventor\b")),
    ("siemens_nx", re.compile(r"\bsiemens\s+nx\b|\bnx\s+cad\b")),
    ("maschinenbau", re.compile(r"\bmaschinenbau\w*")),
    ("mechanical", re.compile(r"\bmechanical\b")),
    ("konstruktion", re.compile(r"\bkonstrukt\w*")),
    ("produktentwicklung", re.compile(r"\bproduktentwick\w*")),
    ("sondermaschinenbau", re.compile(r"\bsondermaschinenbau\w*")),
    ("blechkonstruktion", re.compile(r"\bblechkonstrukt\w*")),
    ("fem", re.compile(r"\bfem\b|\bfinite\s+element")),
    ("berechnung", re.compile(r"\bberechnung\w*")),
    ("anlagenbau", re.compile(r"\banlagenbau\w*")),
    ("maschinenkonstruktion", re.compile(r"\bmaschinenkonstrukt\w*")),
    ("technical_drawing", re.compile(r"\btechnical\s+drawing\w*")),
    ("technische_zeichnung", re.compile(r"\btechnisch\w*\s+zeichnung\w*")),
)


@dataclass(frozen=True, slots=True)
class JobDiscoveryDecision:
    accepted: bool
    reason: str
    strong_title_matches: tuple[str, ...] = ()
    adjacent_title_matches: tuple[str, ...] = ()
    support_matches: tuple[str, ...] = ()


def _matches(patterns: tuple[tuple[str, re.Pattern[str]], ...], text: str) -> tuple[str, ...]:
    return tuple(name for name, pattern in patterns if pattern.search(text))


def classify_job_candidate(job: RawJob) -> JobDiscoveryDecision:
    """Apply a deliberately broad coarse gate before local persistence.

    This is not the final fit model. Its only purpose is to keep the local corpus
    within the broad mechanical-engineering neighbourhood while preserving high
    recall for adjacent roles that can be ranked later from user-reviewed concepts.
    """
    title = _normalize(job.title)
    body = _normalize(job.description)
    combined = f"{title}\n{body}"

    strong_title = _matches(STRONG_TITLE_PATTERNS, title)
    adjacent_title = _matches(ADJACENT_TITLE_PATTERNS, title)
    support = _matches(SUPPORT_PATTERNS, combined)

    if strong_title:
        return JobDiscoveryDecision(
            accepted=True,
            reason="strong_title",
            strong_title_matches=strong_title,
            adjacent_title_matches=adjacent_title,
            support_matches=support,
        )

    if adjacent_title and support:
        return JobDiscoveryDecision(
            accepted=True,
            reason="adjacent_title_with_technical_support",
            strong_title_matches=strong_title,
            adjacent_title_matches=adjacent_title,
            support_matches=support,
        )

    if len(set(support)) >= 2:
        return JobDiscoveryDecision(
            accepted=True,
            reason="multiple_technical_signals",
            strong_title_matches=strong_title,
            adjacent_title_matches=adjacent_title,
            support_matches=support,
        )

    return JobDiscoveryDecision(
        accepted=False,
        reason="insufficient_base_relevance",
        strong_title_matches=strong_title,
        adjacent_title_matches=adjacent_title,
        support_matches=support,
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
        }
        item.raw_payload = payload
        accepted.append(item)
    return accepted
