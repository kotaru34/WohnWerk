from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.jobs.dedupe import (
    DuplicateJobSnapshot,
    duplicate_evidence,
    normalize_company,
    normalize_locality,
)
from app.models import Job, JobListing, JobLocation, ListingStatus

_SALARY_FIELDS = (
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "salary_payment_count",
    "salary_min_eur_year",
    "salary_max_eur_year",
    "salary_text",
    "salary_is_minimum_only",
)


@dataclass(frozen=True, slots=True)
class JobMergePlan:
    job_ids: tuple[int, ...]
    survivor_id: int
    absorbed_ids: tuple[int, ...]
    blockers: tuple[str, ...]
    listings_total: int
    locations_total: int
    salary_source_job_id: int | None

    @property
    def safe(self) -> bool:
        return not self.blockers


@dataclass(frozen=True, slots=True)
class JobMergeResult:
    survivor_id: int
    absorbed_ids: tuple[int, ...]
    listings_moved: int
    locations_moved: int
    locations_deduplicated: int


def _gate_accepted(listing: JobListing) -> bool:
    payload = listing.raw_payload or {}
    gate = payload.get("wohnwerk_discovery_gate")
    return isinstance(gate, dict) and gate.get("accepted") is True


def _snapshot(job: Job, source_names: dict[int, str]) -> DuplicateJobSnapshot:
    return DuplicateJobSnapshot(
        job_id=job.id,
        title=job.title,
        company=job.company,
        description=job.description,
        postal_codes=frozenset(
            row.postal_code for row in job.locations if row.postal_code
        ),
        cities=frozenset(
            canonical
            for row in job.locations
            if (canonical := normalize_locality(row.city))
        ),
        sources=tuple(
            sorted(
                {
                    source_names.get(row.source_id, f"source:{row.source_id}")
                    for row in job.listings
                    if row.status == ListingStatus.ACTIVE and _gate_accepted(row)
                }
            )
        ),
    )


def _salary_signature(job: Job) -> tuple[object, ...] | None:
    values = tuple(getattr(job, field) for field in _SALARY_FIELDS)
    return values if any(value is not None for value in values) else None


def _salary_quality(job: Job) -> tuple[int, Decimal, int]:
    score = 0
    if job.salary_min is not None or job.salary_max is not None:
        score += 4
    if job.salary_min_eur_year is not None or job.salary_max_eur_year is not None:
        score += 4
    if job.salary_period is not None:
        score += 2
    if job.salary_text:
        score += 1
    confidence = job.salary_confidence or Decimal(0)
    provenance = 1 if (job.salary_provenance or "").lower() == "explicit" else 0
    return score, confidence, provenance


def _job_quality(job: Job) -> tuple[int, int, int, int, int]:
    structured_salary = int(
        job.salary_min is not None
        or job.salary_max is not None
        or job.salary_min_eur_year is not None
        or job.salary_max_eur_year is not None
    )
    postal_locations = sum(1 for row in job.locations if row.postal_code)
    geo_locations = sum(1 for row in job.locations if row.location is not None)
    description_length = len(job.description or "")
    listing_count = len(job.listings)
    return (
        structured_salary,
        postal_locations,
        geo_locations,
        description_length,
        listing_count,
    )


def _choose_survivor(jobs: list[Job]) -> Job:
    return max(jobs, key=lambda job: (_job_quality(job), -job.id))


def _choose_salary_source(jobs: list[Job]) -> Job | None:
    candidates = [job for job in jobs if _salary_signature(job) is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda job: (_salary_quality(job), -job.id))


def _salary_blockers(jobs: list[Job]) -> list[str]:
    signatures = {
        signature
        for job in jobs
        if (signature := _salary_signature(job)) is not None
    }
    if len(signatures) <= 1:
        return []
    return ["conflicting canonical salary bundles across merge group"]


def _company_blockers(jobs: list[Job]) -> list[str]:
    normalized = {
        value
        for job in jobs
        if (value := normalize_company(job.company))
    }
    if len(normalized) <= 1:
        return []
    return ["conflicting normalized companies across merge group"]


def _relevant_source_ids(job: Job) -> set[int]:
    return {
        listing.source_id
        for listing in job.listings
        if listing.status == ListingStatus.ACTIVE and _gate_accepted(listing)
    }


def _location_evidence_keys(job: Job) -> set[str]:
    """Return conservative explicit location keys for merge-safety checks.

    Prefer source-backed PLZ/city. If a sparse row has only human-readable text such as
    `Wien, Österreich`, use its first locality component as a fallback. Countrywide and
    remote-only labels normalize to no locality and therefore do not create a conflict.
    """
    keys: set[str] = set()
    for location in job.locations:
        if location.postal_code:
            keys.add(f"plz:{location.postal_code}")
        if city := normalize_locality(location.city):
            keys.add(f"city:{city}")
            continue
        if location.location_text:
            first_component = location.location_text.split(",", 1)[0].strip()
            if fallback := normalize_locality(first_component):
                keys.add(f"city:{fallback}")
    return keys


def _same_source_location_blockers(
    jobs: list[Job],
    source_names: dict[int, str],
) -> list[str]:
    """Block same-source merges when explicit locations disagree.

    Different listing IDs from one source can be parallel openings that reuse the same
    title and staffing template. Strong description overlap alone is therefore not
    enough when their explicit physical locations are disjoint.
    """
    blockers: list[str] = []
    for index, left in enumerate(jobs):
        for right in jobs[index + 1 :]:
            shared_sources = _relevant_source_ids(left) & _relevant_source_ids(right)
            if not shared_sources:
                continue
            left_locations = _location_evidence_keys(left)
            right_locations = _location_evidence_keys(right)
            if not left_locations or not right_locations:
                continue
            if left_locations & right_locations:
                continue
            source_labels = ",".join(
                sorted(source_names.get(source_id, f"source:{source_id}") for source_id in shared_sources)
            )
            blockers.append(
                "same-source explicit locations conflict; "
                f"jobs={left.id},{right.id} sources={source_labels} "
                f"left={','.join(sorted(left_locations))} "
                f"right={','.join(sorted(right_locations))}"
            )
    return blockers


def _evidence_blockers(jobs: list[Job], source_names: dict[int, str]) -> list[str]:
    if len(jobs) < 2:
        return ["merge group must contain at least two jobs"]

    snapshots = {job.id: _snapshot(job, source_names) for job in jobs}
    adjacency: dict[int, set[int]] = {job.id: set() for job in jobs}
    for index, left in enumerate(jobs):
        for right in jobs[index + 1 :]:
            evidence = duplicate_evidence(snapshots[left.id], snapshots[right.id])
            if evidence is not None and evidence.confidence == "high":
                adjacency[left.id].add(right.id)
                adjacency[right.id].add(left.id)

    seen: set[int] = set()
    stack = [jobs[0].id]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency[current] - seen)

    if len(seen) == len(jobs):
        return []
    disconnected = sorted(set(adjacency) - seen)
    return [
        (
            "merge group is not connected by high-confidence duplicate evidence; "
            f"disconnected_job_ids={','.join(map(str, disconnected))}"
        )
    ]


def load_merge_group(session: Session, job_ids: list[int]) -> list[Job]:
    unique_ids = list(dict.fromkeys(job_ids))
    if len(unique_ids) != len(job_ids):
        raise ValueError("merge group contains duplicate job IDs")
    jobs = list(
        session.scalars(
            select(Job)
            .where(Job.id.in_(unique_ids))
            .options(selectinload(Job.listings), selectinload(Job.locations))
        )
    )
    found = {job.id for job in jobs}
    missing = [job_id for job_id in unique_ids if job_id not in found]
    if missing:
        raise ValueError(f"job IDs not found: {','.join(map(str, missing))}")
    return sorted(jobs, key=lambda job: unique_ids.index(job.id))


def build_merge_plan(
    jobs: list[Job],
    *,
    source_names: dict[int, str],
) -> JobMergePlan:
    if len(jobs) < 2:
        raise ValueError("merge group must contain at least two jobs")

    survivor = _choose_survivor(jobs)
    blockers = [
        *_company_blockers(jobs),
        *_salary_blockers(jobs),
        *_same_source_location_blockers(jobs, source_names),
        *_evidence_blockers(jobs, source_names),
    ]
    salary_source = _choose_salary_source(jobs)
    return JobMergePlan(
        job_ids=tuple(job.id for job in jobs),
        survivor_id=survivor.id,
        absorbed_ids=tuple(job.id for job in jobs if job.id != survivor.id),
        blockers=tuple(blockers),
        listings_total=sum(len(job.listings) for job in jobs),
        locations_total=sum(len(job.locations) for job in jobs),
        salary_source_job_id=salary_source.id if salary_source is not None else None,
    )


def _location_matches(left: JobLocation, right: JobLocation) -> bool:
    if left.remote != right.remote:
        return False
    if left.postal_code and right.postal_code:
        return left.postal_code == right.postal_code
    left_city = normalize_locality(left.city)
    right_city = normalize_locality(right.city)
    if left_city and right_city:
        return left_city == right_city
    left_text = " ".join((left.location_text or "").casefold().split())
    right_text = " ".join((right.location_text or "").casefold().split())
    return bool(left_text and left_text == right_text)


def _enrich_location(target: JobLocation, incoming: JobLocation) -> None:
    if target.postal_code is None and incoming.postal_code is not None:
        target.postal_code = incoming.postal_code
    if not target.city and incoming.city:
        target.city = incoming.city
    if not target.location_text and incoming.location_text:
        target.location_text = incoming.location_text
    if target.location is None and incoming.location is not None:
        target.location = incoming.location


def _copy_salary_bundle(target: Job, source: Job) -> None:
    for field in (
        *_SALARY_FIELDS,
        "salary_provenance",
        "salary_confidence",
    ):
        setattr(target, field, getattr(source, field))


def _merge_scalar_fields(survivor: Job, jobs: list[Job], salary_source: Job | None) -> None:
    descriptions = [job.description for job in jobs if job.description]
    if descriptions:
        survivor.description = max(descriptions, key=len)

    companies = [job.company for job in jobs if job.company]
    if companies:
        survivor.company = max(companies, key=len)

    if salary_source is not None:
        _copy_salary_bundle(survivor, salary_source)

    survivor.first_seen_at = min(job.first_seen_at for job in jobs)
    survivor.last_seen_at = max(job.last_seen_at for job in jobs)
    survivor.status = (
        ListingStatus.ACTIVE
        if any(job.status == ListingStatus.ACTIVE for job in jobs)
        else survivor.status
    )
    survivor.inactive_at = (
        None if survivor.status == ListingStatus.ACTIVE else survivor.inactive_at
    )
    survivor.canonical_hash = None

    fit_scores = {job.job_fit_score for job in jobs if job.job_fit_score is not None}
    survivor.job_fit_score = next(iter(fit_scores)) if len(fit_scores) == 1 else None


def apply_merge(
    session: Session,
    jobs: list[Job],
    *,
    source_names: dict[int, str],
) -> JobMergeResult:
    plan = build_merge_plan(jobs, source_names=source_names)
    if not plan.safe:
        raise ValueError("unsafe merge: " + "; ".join(plan.blockers))

    by_id = {job.id: job for job in jobs}
    survivor = by_id[plan.survivor_id]
    absorbed = [by_id[job_id] for job_id in plan.absorbed_ids]
    salary_source = (
        by_id.get(plan.salary_source_job_id) if plan.salary_source_job_id else None
    )
    _merge_scalar_fields(survivor, jobs, salary_source)

    listings_moved = 0
    for job in absorbed:
        for listing in list(job.listings):
            listing.job = survivor
            listings_moved += 1

    locations_moved = 0
    locations_deduplicated = 0
    for job in absorbed:
        for location in list(job.locations):
            existing = next(
                (row for row in survivor.locations if _location_matches(row, location)),
                None,
            )
            if existing is not None:
                _enrich_location(existing, location)
                session.delete(location)
                locations_deduplicated += 1
            else:
                location.job = survivor
                locations_moved += 1

    session.flush()
    for job in absorbed:
        session.delete(job)
    session.commit()

    return JobMergeResult(
        survivor_id=survivor.id,
        absorbed_ids=plan.absorbed_ids,
        listings_moved=listings_moved,
        locations_moved=locations_moved,
        locations_deduplicated=locations_deduplicated,
    )
