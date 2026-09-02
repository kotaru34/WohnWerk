from __future__ import annotations

import argparse
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.jobs.dedupe import DuplicateJobSnapshot, duplicate_evidence, normalize_locality
from app.jobs.merge import build_merge_plan
from app.models import Job, JobListing, ListingStatus, Source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only audit of likely duplicate canonical jobs across and within sources."
    )
    parser.add_argument(
        "--include-medium",
        action="store_true",
        help="Also print medium-confidence candidates (high-confidence is always shown).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum candidate pairs to print (default: 100).",
    )
    return parser.parse_args()


def _gate_accepted(listing: JobListing) -> bool:
    payload = listing.raw_payload or {}
    gate = payload.get("wohnwerk_discovery_gate")
    return isinstance(gate, dict) and gate.get("accepted") is True


def _relevant_active_listings(job: Job) -> list[JobListing]:
    return [
        listing
        for listing in job.listings
        if listing.status == ListingStatus.ACTIVE and _gate_accepted(listing)
    ]


def _snapshot(job: Job, source_names: dict[int, str]) -> DuplicateJobSnapshot:
    postals = frozenset(
        location.postal_code for location in job.locations if location.postal_code
    )
    cities = frozenset(
        normalized
        for location in job.locations
        if (normalized := normalize_locality(location.city))
    )
    sources = tuple(
        sorted(
            {
                source_names.get(listing.source_id, f"source:{listing.source_id}")
                for listing in _relevant_active_listings(job)
            }
        )
    )
    return DuplicateJobSnapshot(
        job_id=job.id,
        title=job.title,
        company=job.company,
        description=job.description,
        postal_codes=postals,
        cities=cities,
        sources=sources,
    )


def _location_label(snapshot: DuplicateJobSnapshot) -> str:
    parts: list[str] = []
    if snapshot.postal_codes:
        parts.append("plz=" + ",".join(sorted(snapshot.postal_codes)))
    if snapshot.cities:
        parts.append("city=" + ",".join(sorted(snapshot.cities)))
    return " ".join(parts) or "-"


def _print_listing_refs(job: Job, source_names: dict[int, str]) -> None:
    for listing in _relevant_active_listings(job):
        source_name = source_names.get(listing.source_id, f"source:{listing.source_id}")
        print(
            f"      listing source={source_name} id={listing.source_listing_id} "
            f"url={listing.url}"
        )


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        source_names = dict(session.execute(select(Source.id, Source.name)).all())
        jobs = list(
            session.scalars(
                select(Job)
                .where(Job.status == ListingStatus.ACTIVE)
                .options(selectinload(Job.listings), selectinload(Job.locations))
                .order_by(Job.id)
            )
        )

        relevant_jobs = [job for job in jobs if _relevant_active_listings(job)]
        snapshots = [_snapshot(job, source_names) for job in relevant_jobs]
        jobs_by_id = {job.id: job for job in relevant_jobs}

        already_multi_listing = sum(
            1 for job in relevant_jobs if len(_relevant_active_listings(job)) > 1
        )

        high = []
        blocked = []
        medium = []
        snapshot_by_id = {item.job_id: item for item in snapshots}
        for left, right in combinations(snapshots, 2):
            evidence = duplicate_evidence(left, right)
            if evidence is None:
                continue
            if evidence.confidence == "high":
                plan = build_merge_plan(
                    [jobs_by_id[left.job_id], jobs_by_id[right.job_id]],
                    source_names=source_names,
                )
                if plan.safe:
                    high.append(evidence)
                else:
                    blocked.append((evidence, plan.blockers))
            else:
                medium.append(evidence)

        high.sort(
            key=lambda item: (-item.title_similarity, item.left_job_id, item.right_job_id)
        )
        blocked.sort(
            key=lambda item: (
                -item[0].title_similarity,
                item[0].left_job_id,
                item[0].right_job_id,
            )
        )
        medium.sort(
            key=lambda item: (-item.title_similarity, item.left_job_id, item.right_job_id)
        )

        print(f"relevant_canonical_jobs={len(relevant_jobs)}")
        print(f"already_multi_listing_canonical_jobs={already_multi_listing}")
        print(f"duplicate_candidates_high={len(high)}")
        print(f"duplicate_candidates_blocked={len(blocked)}")
        print(f"duplicate_candidates_medium={len(medium)}")
        print("mode=read-only no database changes")

        candidates = [
            ("high", evidence, ()) for evidence in high
        ] + [
            ("blocked", evidence, blockers) for evidence, blockers in blocked
        ]
        if args.include_medium:
            candidates.extend(("medium", evidence, ()) for evidence in medium)

        for index, (classification, evidence, blockers) in enumerate(
            candidates[: max(0, args.limit)], start=1
        ):
            left = snapshot_by_id[evidence.left_job_id]
            right = snapshot_by_id[evidence.right_job_id]
            print()
            print(
                f"[{index}] confidence={classification} "
                f"evidence_confidence={evidence.confidence} "
                f"similarity={evidence.title_similarity:.3f} "
                f"description_similarity={evidence.description_similarity:.3f} "
                f"generic_title={'yes' if evidence.generic_title else 'no'} "
                f"shared_source={'yes' if evidence.shared_source else 'no'} "
                f"reasons={','.join(evidence.reasons)}"
            )
            print(
                f"  left job={left.job_id} sources={','.join(left.sources) or '-'} "
                f"company={left.company or '-'} location={_location_label(left)}"
            )
            print(f"    {left.title}")
            _print_listing_refs(jobs_by_id[left.job_id], source_names)
            print(
                f"  right job={right.job_id} sources={','.join(right.sources) or '-'} "
                f"company={right.company or '-'} location={_location_label(right)}"
            )
            print(f"    {right.title}")
            _print_listing_refs(jobs_by_id[right.job_id], source_names)
            if blockers:
                print("  merge_blockers:")
                for blocker in blockers:
                    print(f"    - {blocker}")


if __name__ == "__main__":
    main()
