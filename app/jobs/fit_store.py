from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.candidate_activity import is_new_unviewed, load_job_viewed_ids, novelty_baseline
from app.jobs.candidate_fit import FitEvidence, JobFitResult, score_job_concepts
from app.jobs.candidate_job_store import load_candidate_job_states
from app.jobs.candidate_profile_seed import PROFILE_SLUG
from app.jobs.candidate_profile_store import get_profile, load_profile_preferences
from app.jobs.concept_catalog import EXTRACTOR_VERSION
from app.jobs.concepts import ConceptKind, JobConcept, JobConceptEvidence
from app.models import Job, JobListing, ListingStatus, Source


@dataclass(frozen=True, slots=True)
class JobSourceLink:
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class JobFitDriverView:
    label_de: str
    contribution: float


@dataclass(frozen=True, slots=True)
class JobFitView:
    job: Job
    result: JobFitResult
    locations: tuple[str, ...]
    links: tuple[JobSourceLink, ...]
    drivers: tuple[JobFitDriverView, ...]
    hard_labels: tuple[str, ...]
    favorite: bool = False
    hidden: bool = False
    viewed: bool = False
    is_new: bool = False


def _gate_accepted(listing: JobListing) -> bool:
    payload = listing.raw_payload or {}
    gate = payload.get("wohnwerk_discovery_gate")
    return isinstance(gate, dict) and gate.get("accepted") is True


def _listing_is_catalog_eligible(
    listing: JobListing,
    enabled_source_ids: set[int],
) -> bool:
    """Keep source lifecycle and user-visible relevance as explicit prerequisites."""
    return (
        listing.source_id in enabled_source_ids
        and listing.status == ListingStatus.ACTIVE
        and _gate_accepted(listing)
    )


def relevant_active_jobs(session: Session) -> list[Job]:
    """Return jobs backed by an enabled, active, discovery-accepted source listing."""

    enabled_source_ids = set(
        session.scalars(select(Source.id).where(Source.enabled.is_(True)))
    )
    if not enabled_source_ids:
        return []

    jobs = list(
        session.scalars(
            select(Job)
            .where(Job.status == ListingStatus.ACTIVE)
            .options(selectinload(Job.listings), selectinload(Job.locations))
            .order_by(Job.id)
        )
    )
    return [
        job
        for job in jobs
        if any(
            _listing_is_catalog_eligible(listing, enabled_source_ids)
            for listing in job.listings
        )
    ]


def persisted_evidence_by_job(
    session: Session,
    job_ids: set[int],
) -> dict[int, list[FitEvidence]]:
    result: dict[int, list[FitEvidence]] = defaultdict(list)
    if not job_ids:
        return result

    rows = session.execute(
        select(JobConceptEvidence, JobConcept)
        .join(JobConcept, JobConcept.id == JobConceptEvidence.concept_id)
        .where(
            JobConceptEvidence.job_id.in_(job_ids),
            JobConceptEvidence.extractor_version == EXTRACTOR_VERSION,
            JobConcept.enabled.is_(True),
        )
        .order_by(JobConceptEvidence.job_id, JobConcept.kind, JobConcept.slug)
    ).all()
    for evidence, concept in rows:
        result[evidence.job_id].append(
            FitEvidence(
                kind=ConceptKind(concept.kind),
                slug=concept.slug,
                scope=evidence.scope,
                confidence=float(evidence.confidence),
            )
        )
    return result


def _location_labels(job: Job) -> tuple[str, ...]:
    labels: list[str] = []
    for location in job.locations:
        parts: list[str] = []
        if location.postal_code:
            parts.append(location.postal_code)
        if location.city:
            parts.append(location.city)
        label = " ".join(parts) or (location.location_text or "").strip()
        if location.remote:
            label = f"{label} · Remote" if label else "Remote"
        if label and label not in labels:
            labels.append(label)
    return tuple(labels)


def _source_links(session: Session, jobs: list[Job]) -> dict[int, tuple[JobSourceLink, ...]]:
    source_ids = {
        listing.source_id
        for job in jobs
        for listing in job.listings
        if listing.status == ListingStatus.ACTIVE
    }
    source_names = (
        {
            source.id: source.name
            for source in session.scalars(
                select(Source).where(
                    Source.id.in_(source_ids),
                    Source.enabled.is_(True),
                )
            )
        }
        if source_ids
        else {}
    )
    enabled_source_ids = set(source_names)

    result: dict[int, tuple[JobSourceLink, ...]] = {}
    for job in jobs:
        links: list[JobSourceLink] = []
        seen_urls: set[str] = set()
        for listing in job.listings:
            if (
                not _listing_is_catalog_eligible(listing, enabled_source_ids)
                or not listing.url
                or listing.url in seen_urls
            ):
                continue
            seen_urls.add(listing.url)
            links.append(
                JobSourceLink(
                    label=source_names.get(listing.source_id, f"Quelle {listing.source_id}"),
                    url=listing.url,
                )
            )
        result[job.id] = tuple(links)
    return result


def _concept_labels(session: Session) -> dict[tuple[ConceptKind, str], str]:
    return {
        (ConceptKind(concept.kind), concept.slug): concept.label_de
        for concept in session.scalars(select(JobConcept).where(JobConcept.enabled.is_(True)))
    }


def load_live_job_fit(
    session: Session,
    *,
    profile_slug: str = PROFILE_SLUG,
) -> list[JobFitView]:
    """Recompute current persisted-profile fit without writing a cache to Job.job_fit_score."""

    preferences = load_profile_preferences(session, profile_slug)
    profile = get_profile(session, profile_slug)
    if profile is None or not profile.enabled:
        raise ValueError(f"candidate profile is unavailable: {profile_slug}")

    jobs = relevant_active_jobs(session)
    job_ids = {job.id for job in jobs}
    evidence = persisted_evidence_by_job(session, job_ids)
    links_by_job = _source_links(session, jobs)
    labels = _concept_labels(session)
    states = load_candidate_job_states(session, profile.id, job_ids)
    viewed_ids = load_job_viewed_ids(session, profile.id, job_ids)
    baseline = novelty_baseline(session, profile)

    views: list[JobFitView] = []
    for job in jobs:
        result = score_job_concepts(evidence.get(job.id, []), preferences)
        drivers = tuple(
            JobFitDriverView(
                label_de=labels.get((item.kind, item.slug), item.slug),
                contribution=item.contribution,
            )
            for item in result.contributions[:4]
        )
        hard_labels = tuple(
            labels.get((item.kind, item.slug), item.slug) for item in result.hard_constraints
        )
        state = states.get(job.id)
        viewed = job.id in viewed_ids
        views.append(
            JobFitView(
                job=job,
                result=result,
                locations=_location_labels(job),
                links=links_by_job.get(job.id, ()),
                drivers=drivers,
                hard_labels=hard_labels,
                favorite=state.favorite if state is not None else False,
                hidden=state.hidden if state is not None else False,
                viewed=viewed,
                is_new=is_new_unviewed(
                    first_seen_at=job.first_seen_at,
                    baseline=baseline,
                    viewed_at=job.first_seen_at if viewed else None,
                ),
            )
        )

    views.sort(
        key=lambda view: (
            view.hidden,
            not view.favorite,
            view.result.score is None,
            bool(view.result.hard_constraints),
            -(view.result.score or 0),
            -view.result.preference_coverage,
            view.job.id,
        )
    )
    return views


def _eur(value: Decimal) -> str:
    if value == value.to_integral_value():
        return f"{int(value):,}".replace(",", ".") + " €"
    formatted = f"{value:,.2f}"
    formatted = formatted.replace(",", "_").replace(".", ",").replace("_", ".")
    return formatted + " €"


def annual_salary_label(job: Job) -> str | None:
    """Format the source-backed salary in its own period; legacy name kept for templates.

    Monthly salary is shown as monthly rather than being silently multiplied by 12 or 14.
    Annualized fields remain a fallback only when the original source dimensions are absent.
    """
    period_labels = {
        "month": "Monat",
        "year": "Jahr",
        "hour": "Stunde",
        "week": "Woche",
        "day": "Tag",
    }
    period = (job.salary_period or "").lower()
    currency = (job.salary_currency or "").upper()
    minimum = job.salary_min
    maximum = job.salary_max

    if currency == "EUR" and period in period_labels and (minimum is not None or maximum is not None):
        if minimum is not None and maximum is not None and minimum != maximum:
            amount = f"{_eur(minimum)} – {_eur(maximum)}"
        elif minimum is not None:
            prefix = "ab " if job.salary_is_minimum_only else ""
            amount = f"{prefix}{_eur(minimum)}"
        elif maximum is not None:
            amount = f"bis {_eur(maximum)}"
        else:
            return None

        label = f"{amount} / {period_labels[period]}"
        if period == "month" and job.salary_payment_count:
            label += f" · {job.salary_payment_count}×"
        return label

    minimum = job.salary_min_eur_year
    maximum = job.salary_max_eur_year
    if minimum is None and maximum is None:
        return None
    if minimum is not None and maximum is not None and minimum != maximum:
        return f"{_eur(minimum)} – {_eur(maximum)} / Jahr"
    value = minimum if minimum is not None else maximum
    if value is None:
        return None
    prefix = "ab " if job.salary_is_minimum_only else ""
    return f"{prefix}{_eur(value)} / Jahr"
