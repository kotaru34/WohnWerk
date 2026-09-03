from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import exists, func, select, update

from app.database import SessionLocal
from app.jobs.location_resolution import canonicalize_locality
from app.live_events import queue_live_event
from app.models import Job, JobListing, ListingStatus, PostalCode, Source
from app.sources.job.personio import _austrian_locations

SOURCE_NAME = "personio-public-xml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit or deactivate Personio listings that were admitted after the shared "
            "DE postal reference polluted the Austria-only locality proof."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Deactivate confirmed out-of-scope Personio listings. Default is read-only.",
    )
    return parser.parse_args()


def _austrian_localities(session) -> set[str]:
    names = set(
        session.scalars(
            select(PostalCode.name).where(func.length(PostalCode.postal_code) == 4)
        )
    )
    return {
        canonical
        for value in names
        if (canonical := canonicalize_locality(value)) is not None
    }


def _contaminated_rows(session, source: Source) -> list[tuple[JobListing, Job, str]]:
    localities = _austrian_localities(session)
    rows = session.execute(
        select(JobListing, Job)
        .join(Job, Job.id == JobListing.job_id)
        .where(
            JobListing.source_id == source.id,
            JobListing.status == ListingStatus.ACTIVE,
        )
        .order_by(JobListing.id)
    )

    contaminated: list[tuple[JobListing, Job, str]] = []
    for listing, job in rows:
        payload = listing.raw_payload or {}
        office = payload.get("personio_office")
        if not isinstance(office, str) or not office.strip():
            continue
        if _austrian_locations(office, austrian_localities=localities):
            continue
        contaminated.append((listing, job, office.strip()))
    return contaminated


def main() -> None:
    args = parse_args()
    now = datetime.now(UTC)

    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        if source is None:
            raise SystemExit(f"Source {SOURCE_NAME!r} not found")

        rows = _contaminated_rows(session, source)
        print(f"source={SOURCE_NAME}")
        print(f"out_of_scope_active={len(rows)}")
        for listing, job, office in rows:
            print(
                f"listing={listing.id} job={job.id} source_id={listing.source_listing_id} "
                f"office={office!r} title={job.title!r} url={listing.url}"
            )

        if not args.apply:
            print("repair_status=dry-run")
            return

        listing_ids = [listing.id for listing, _job, _office in rows]
        job_ids = {job.id for _listing, job, _office in rows}
        if listing_ids:
            session.execute(
                update(JobListing)
                .where(JobListing.id.in_(listing_ids))
                .values(status=ListingStatus.INACTIVE, inactive_at=now)
            )

        deactivated_jobs = 0
        for job_id in sorted(job_ids):
            has_active_listing = session.scalar(
                select(
                    exists().where(
                        JobListing.job_id == job_id,
                        JobListing.status == ListingStatus.ACTIVE,
                    )
                )
            )
            if has_active_listing:
                continue
            result = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == ListingStatus.ACTIVE)
                .values(status=ListingStatus.INACTIVE, inactive_at=now)
            )
            deactivated_jobs += result.rowcount or 0

        if rows:
            queue_live_event(
                session,
                topic="jobs",
                kind="catalog_refresh",
                payload={
                    "source": SOURCE_NAME,
                    "repair": "austria_locality_scope",
                    "listings_deactivated": len(listing_ids),
                    "jobs_deactivated": deactivated_jobs,
                },
            )

        session.commit()
        print(f"listings_deactivated={len(listing_ids)}")
        print(f"jobs_deactivated={deactivated_jobs}")
        print("repair_status=applied")


if __name__ == "__main__":
    main()
