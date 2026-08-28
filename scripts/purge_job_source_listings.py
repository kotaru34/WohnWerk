from __future__ import annotations

import argparse

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Job, JobListing, Source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Disable one job source and remove listings acquired from it. "
            "Dry-run by default; apply refuses shared canonical jobs."
        )
    )
    parser.add_argument("source", help="Source name, for example karriere.at")
    parser.add_argument("--apply", action="store_true", help="Actually modify the database")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == args.source))
        if source is None:
            raise SystemExit(f"Unknown source: {args.source}")

        rows = list(
            session.execute(
                select(JobListing.id, JobListing.job_id, Job.title)
                .join(Job, Job.id == JobListing.job_id)
                .where(JobListing.source_id == source.id)
                .order_by(JobListing.job_id, JobListing.id)
            )
        )
        affected_job_ids = sorted({row.job_id for row in rows})

        shared: list[tuple[int, str, int]] = []
        exclusive: list[tuple[int, str]] = []
        for job_id in affected_job_ids:
            title = next(row.title for row in rows if row.job_id == job_id)
            listing_count = session.scalar(
                select(func.count(JobListing.id)).where(JobListing.job_id == job_id)
            ) or 0
            if listing_count > 1:
                shared.append((job_id, title, listing_count))
            else:
                exclusive.append((job_id, title))

        print(f"source={source.name} enabled={source.enabled}")
        print(f"source_listings={len(rows)} affected_jobs={len(affected_job_ids)}")
        print(f"exclusive_jobs={len(exclusive)} shared_jobs={len(shared)}")
        if shared:
            print("shared_jobs_need_review:")
            for job_id, title, listing_count in shared:
                print(f"  job_id={job_id} listings={listing_count} title={title}")

        if not args.apply:
            print("dry_run=yes; rerun with --apply only when shared_jobs=0")
            return

        if shared:
            raise SystemExit(
                "Refusing purge: shared canonical jobs require manual canonical-field review first"
            )

        source.enabled = False
        source.config = {
            **(source.config or {}),
            "automated_acquisition_allowed": False,
            "purged_source_listings": True,
        }

        listing_ids = [row.id for row in rows]
        if listing_ids:
            for listing in session.scalars(
                select(JobListing).where(JobListing.id.in_(listing_ids))
            ):
                session.delete(listing)
            session.flush()

        deleted_jobs = 0
        for job_id in affected_job_ids:
            job = session.get(Job, job_id)
            if job is not None:
                session.delete(job)
                deleted_jobs += 1

        session.commit()
        print(f"disabled_source=yes purged_listings={len(rows)} deleted_jobs={deleted_jobs}")
        print("shared_jobs=0 purge_safe=yes")


if __name__ == "__main__":
    main()
