from __future__ import annotations

from app.jobs.discovery import classify_job_candidate
from app.jobs.salary import parse_salary_text
from app.sources.base import RawJob


def raw_job_has_explicit_salary(item: RawJob) -> bool:
    """Return whether the search/API payload already contains usable salary evidence."""
    if (
        item.salary_min is not None
        and item.salary_currency is not None
        and item.salary_period is not None
    ):
        return True
    if parse_salary_text(item.salary_text, trusted=True) is not None:
        return True
    return parse_salary_text(item.description) is not None


def salary_detail_candidates(items: list[RawJob]) -> list[RawJob]:
    """Choose only discovery-accepted, salary-missing jobs for detail enrichment.

    Search-card frontiers are already bounded by their first-page shards. Detail requests
    should therefore follow the same semantic gate that decides whether a vacancy can enter
    WohnWerk, rather than a second title regex or the arbitrary position of a hit inside the
    first eight detail-worthy results.
    """
    selected: list[RawJob] = []
    seen: set[str] = set()

    for item in items:
        if item.source_listing_id in seen:
            continue
        seen.add(item.source_listing_id)
        if raw_job_has_explicit_salary(item):
            continue
        if not classify_job_candidate(item).accepted:
            continue
        selected.append(item)

    return selected
