from __future__ import annotations

import argparse

from sqlalchemy import select

from app.database import SessionLocal
from app.jobs.candidate_job_store import merge_candidate_job_states
from app.jobs.merge import apply_merge, build_merge_plan, load_merge_group
from app.models import Source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fail-closed canonical Job merge. Dry-run by default; provide explicit job IDs "
            "from the duplicate audit and use --apply only after inspecting the plan."
        )
    )
    parser.add_argument(
        "job_ids",
        nargs="+",
        type=int,
        help="Two or more canonical Job IDs that should represent one vacancy.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the merge. Without this flag the command is read-only.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        source_names = dict(session.execute(select(Source.id, Source.name)).all())
        jobs = load_merge_group(session, args.job_ids)
        plan = build_merge_plan(jobs, source_names=source_names)

        print(f"job_ids={','.join(map(str, plan.job_ids))}")
        print(f"survivor_id={plan.survivor_id}")
        print(f"absorbed_ids={','.join(map(str, plan.absorbed_ids))}")
        print(f"listings_total={plan.listings_total} locations_total={plan.locations_total}")
        print(f"salary_source_job_id={plan.salary_source_job_id or '-'}")
        print(f"safe={'yes' if plan.safe else 'no'}")

        for job in jobs:
            print()
            print(f"job={job.id} company={job.company or '-'}")
            print(f"  title={job.title}")
            print(
                f"  description_length={len(job.description or '')} "
                f"salary_min={job.salary_min} salary_max={job.salary_max} "
                f"salary_period={job.salary_period or '-'}"
            )
            for location in job.locations:
                print(
                    "  location="
                    f"plz={location.postal_code or '-'} city={location.city or '-'} "
                    f"text={location.location_text or '-'} remote={location.remote}"
                )
            for listing in job.listings:
                source_name = source_names.get(listing.source_id, f"source:{listing.source_id}")
                print(
                    f"  listing={source_name}:{listing.source_listing_id} "
                    f"status={listing.status} url={listing.url}"
                )

        if plan.blockers:
            print()
            print("blockers:")
            for blocker in plan.blockers:
                print(f"  - {blocker}")

        if not args.apply:
            print()
            print("mode=dry-run no database changes")
            return

        if not plan.safe:
            raise SystemExit("Refusing merge: plan is not fail-closed safe")

        # Keep candidate curation in the same transaction as the canonical merge. If the
        # merge raises, the Session context rolls these uncommitted state moves back too.
        merge_candidate_job_states(
            session,
            survivor_id=plan.survivor_id,
            absorbed_ids=plan.absorbed_ids,
        )
        result = apply_merge(session, jobs, source_names=source_names)
        print()
        print("mode=apply")
        print(f"merged_survivor={result.survivor_id}")
        print(f"deleted_jobs={','.join(map(str, result.absorbed_ids))}")
        print(f"listings_moved={result.listings_moved}")
        print(f"locations_moved={result.locations_moved}")
        print(f"locations_deduplicated={result.locations_deduplicated}")


if __name__ == "__main__":
    main()
