from __future__ import annotations

import argparse
from collections import defaultdict
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.jobs.candidate_fit import DEFAULT_FIT_POLICY, FitEvidence, JobFitResult, score_job_concepts
from app.jobs.candidate_profile_seed import PROFILE_PREFERENCES, PROFILE_SEED_VERSION
from app.jobs.concept_catalog import (
    CONCEPT_SEEDS,
    EXTRACTOR_VERSION,
    JobTextSnapshot,
    extract_concepts,
)
from app.jobs.concepts import (
    ConceptKind,
    JobConcept,
    JobConceptEvidence,
    concept_evidence_semantics,
)
from app.models import Job, JobListing, ListingStatus


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only candidate fit audit from normalized concept evidence."
    )
    parser.add_argument(
        "--limit", type=int, default=20, help="Top/bottom jobs to print (default: 20)."
    )
    parser.add_argument(
        "--job-id",
        type=int,
        action="append",
        default=[],
        help="Print full scored concept contribution detail for a Job ID; may be repeated.",
    )
    parser.add_argument(
        "--preview-current-extractor",
        action="store_true",
        help=(
            "Compute evidence in memory from the current seed extractor instead of requiring "
            "that extractor version to already be persisted. Read-only."
        ),
    )
    return parser.parse_args()


def _gate_accepted(listing: JobListing) -> bool:
    payload = listing.raw_payload or {}
    gate = payload.get("wohnwerk_discovery_gate")
    return isinstance(gate, dict) and gate.get("accepted") is True


def _relevant_active_jobs(session) -> list[Job]:
    jobs = list(
        session.scalars(
            select(Job)
            .where(Job.status == ListingStatus.ACTIVE)
            .options(selectinload(Job.listings))
            .order_by(Job.id)
        )
    )
    return [
        job
        for job in jobs
        if any(
            listing.status == ListingStatus.ACTIVE and _gate_accepted(listing)
            for listing in job.listings
        )
    ]


def _persisted_evidence_by_job(session, job_ids: set[int]) -> dict[int, list[FitEvidence]]:
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


def _preview_evidence_by_job(jobs: list[Job]) -> dict[int, list[FitEvidence]]:
    result: dict[int, list[FitEvidence]] = defaultdict(list)
    for job in jobs:
        matches = extract_concepts(
            JobTextSnapshot(job_id=job.id, title=job.title, description=job.description)
        )
        for match in matches:
            scope, confidence = concept_evidence_semantics(match.kind, match.field)
            result[job.id].append(
                FitEvidence(
                    kind=match.kind,
                    slug=match.slug,
                    scope=scope.value,
                    confidence=confidence,
                )
            )
    return result


def _seed_validation(session, *, preview: bool) -> tuple[int, list[str]]:
    if preview:
        concepts = {(seed.kind, seed.slug) for seed in CONCEPT_SEEDS}
    else:
        concepts = {
            (ConceptKind(concept.kind), concept.slug)
            for concept in session.scalars(select(JobConcept).where(JobConcept.enabled.is_(True)))
        }
    missing = [
        f"{kind.value}:{slug}"
        for kind, slug in PROFILE_PREFERENCES
        if (kind, slug) not in concepts
    ]
    return len(PROFILE_PREFERENCES), sorted(missing)


def _driver_label(result: JobFitResult, limit: int = 5) -> str:
    return ", ".join(
        f"{item.kind.value}:{item.slug}={item.state.value}({item.contribution:+.2f})"
        for item in result.contributions[:limit]
    ) or "-"


def _hard_label(result: JobFitResult) -> str:
    return ",".join(f"{item.kind.value}:{item.slug}" for item in result.hard_constraints) or "-"


def _print_job(job: Job, result: JobFitResult) -> None:
    score = "-" if result.score is None else str(result.score)
    print(
        f"  job={job.id} score={score} coverage={result.preference_coverage:.3f} "
        f"hard_incompatible={'yes' if result.hard_constraints else 'no'} "
        f"company={job.company or '-'} title={job.title}"
    )
    print(f"    drivers={_driver_label(result)}")
    if result.hard_constraints:
        print(f"    hard_constraints={_hard_label(result)}")


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        jobs = _relevant_active_jobs(session)
        jobs_by_id = {job.id: job for job in jobs}
        if args.preview_current_extractor:
            evidence_by_job = _preview_evidence_by_job(jobs)
            evidence_mode = "preview_current_extractor"
        else:
            evidence_by_job = _persisted_evidence_by_job(session, set(jobs_by_id))
            evidence_mode = "persisted_current_extractor"

        ratings_count, missing_seed = _seed_validation(
            session, preview=args.preview_current_extractor
        )
        results = {
            job.id: score_job_concepts(evidence_by_job.get(job.id, []), PROFILE_PREFERENCES)
            for job in jobs
        }

        scored = [result for result in results.values() if result.score is not None]
        hard_incompatible = [result for result in scored if result.hard_constraints]
        print(f"profile_seed_version={PROFILE_SEED_VERSION}")
        print(f"fit_policy_version={DEFAULT_FIT_POLICY.version}")
        print(f"extractor_version={EXTRACTOR_VERSION}")
        print(f"evidence_mode={evidence_mode}")
        print(f"rated_concepts={ratings_count}")
        print(f"missing_seed_concepts={','.join(missing_seed) if missing_seed else '-'}")
        print(
            "state_values="
            + ",".join(
                f"{state.value}:{value:+.2f}"
                for state, value in DEFAULT_FIT_POLICY.state_values.items()
            )
        )
        print(
            "scope_weights="
            + ",".join(
                f"{scope}:{weight:.2f}"
                for scope, weight in DEFAULT_FIT_POLICY.scope_weights.items()
            )
        )
        print(f"positive_evidence_budget={DEFAULT_FIT_POLICY.positive_evidence_budget:.2f}")
        print(
            "hard_incompatibility_kinds="
            + ",".join(
                sorted(kind.value for kind in DEFAULT_FIT_POLICY.hard_incompatibility_kinds)
            )
        )
        print(
            "hard_primary_incompatibility_cap="
            f"{DEFAULT_FIT_POLICY.hard_primary_incompatibility_cap}"
        )
        print(f"relevant_active_jobs={len(jobs)}")
        print(f"jobs_scored={len(scored)}")
        print(f"jobs_unscored={len(jobs) - len(scored)}")
        print(f"jobs_hard_incompatible={len(hard_incompatible)}")
        if not args.preview_current_extractor and not any(evidence_by_job.values()):
            print(
                "warning=no persisted evidence for current extractor; "
                "use --preview-current-extractor or persist normalization first"
            )
        if scored:
            print(f"score_mean={mean(result.score for result in scored if result.score is not None):.2f}")
            print(
                "score_median="
                f"{median(result.score for result in scored if result.score is not None):.2f}"
            )
            print(
                "preference_coverage_mean="
                f"{mean(result.preference_coverage for result in scored):.3f}"
            )
            print(
                "preference_coverage_median="
                f"{median(result.preference_coverage for result in scored):.3f}"
            )

        ranked = [
            (job, results[job.id])
            for job in jobs
            if results[job.id].score is not None
        ]
        ranked.sort(
            key=lambda pair: (
                -(pair[1].score or 0),
                -pair[1].preference_coverage,
                pair[0].id,
            )
        )
        limit = max(0, args.limit)
        print("top_jobs:")
        for job, result in ranked[:limit]:
            _print_job(job, result)

        print("bottom_jobs:")
        for job, result in sorted(
            ranked,
            key=lambda pair: (
                pair[1].score or 0,
                -pair[1].preference_coverage,
                pair[0].id,
            ),
        )[:limit]:
            _print_job(job, result)

        if args.job_id:
            print("audited_jobs:")
            for job_id in args.job_id:
                job = jobs_by_id.get(job_id)
                if job is None:
                    print(f"  job={job_id} not_relevant_or_missing=yes")
                    continue
                result = results[job_id]
                _print_job(job, result)
                for item in result.contributions:
                    print(
                        f"      contribution {item.kind.value}:{item.slug} "
                        f"state={item.state.value} scope={item.scope} "
                        f"evidence_weight={item.evidence_weight:.3f} "
                        f"value={item.contribution:+.3f}"
                    )
                print("      evidence:")
                for item in evidence_by_job.get(job_id, []):
                    state = PROFILE_PREFERENCES.get((item.kind, item.slug))
                    state_label = state.value if state is not None else "unrated"
                    print(
                        f"        {item.kind.value}:{item.slug} scope={item.scope} "
                        f"confidence={item.confidence:.2f} preference={state_label}"
                    )

        print("mode=read-only no database changes")


if __name__ == "__main__":
    main()
