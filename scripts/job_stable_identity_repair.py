from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.jobs.identity import stable_identity_from_payload, with_stable_identity
from app.jobs.liveness import parse_iso_datetime
from app.models import Job, JobListing, ListingStatus, Source

_SOURCE_NAME = "smartrecruiters-public-postings"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit and optionally repair canonical jobs duplicated by SmartRecruiters republishes."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply identity backfill and merge duplicate canonical jobs. Default is dry-run.",
    )
    return parser.parse_args()


def _released_at(listing: JobListing) -> datetime | None:
    return parse_iso_datetime((listing.raw_payload or {}).get("smartrecruiters_released_date"))


def _survivor_listing(listings: list[JobListing]) -> JobListing:
    """Prefer the newest released/current listing as canonical metadata owner."""
    return max(
        listings,
        key=lambda row: (
            _released_at(row) or row.last_seen_at,
            row.last_seen_at,
            row.id,
        ),
    )


def _merge_missing_job_fields(survivor: Job, duplicate: Job) -> None:
    # Never transfer canonical_hash here: it is unique and represents a canonical
    # row identity, not source evidence. A republish merge keeps the survivor's
    # hash (or lack of one) and deletes the duplicate row.
    scalar_fields = (
        "company",
        "description",
        "salary_text",
        "salary_min",
        "salary_max",
        "salary_currency",
        "salary_period",
        "salary_payment_count",
        "salary_provenance",
        "salary_confidence",
        "salary_min_eur_year",
        "salary_max_eur_year",
        "salary_is_minimum_only",
        "job_fit_score",
    )
    for field in scalar_fields:
        if getattr(survivor, field) is None and getattr(duplicate, field) is not None:
            setattr(survivor, field, getattr(duplicate, field))

    survivor.first_seen_at = min(survivor.first_seen_at, duplicate.first_seen_at)
    survivor.last_seen_at = max(survivor.last_seen_at, duplicate.last_seen_at)
    if duplicate.status == ListingStatus.ACTIVE:
        survivor.status = ListingStatus.ACTIVE
        survivor.inactive_at = None


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == _SOURCE_NAME))
        if source is None:
            print(f"source_not_found={_SOURCE_NAME}")
            return

        listings = list(
            session.scalars(
                select(JobListing)
                .where(JobListing.source_id == source.id)
                .options(selectinload(JobListing.job))
                .order_by(JobListing.id)
            )
        )

        groups: dict[str, list[JobListing]] = defaultdict(list)
        identity_rows = 0
        missing_identity = 0
        needs_backfill = 0

        for listing in listings:
            payload = listing.raw_payload or {}
            identity = stable_identity_from_payload(payload)
            if identity is None:
                missing_identity += 1
                continue
            identity_rows += 1
            groups[identity].append(listing)
            if payload.get("wohnwerk_stable_identity") != identity:
                needs_backfill += 1

        duplicate_groups = {
            identity: rows
            for identity, rows in groups.items()
            if len({row.job_id for row in rows}) > 1
        }

        print(f"source={source.name}")
        print(f"listings={len(listings)} identity_rows={identity_rows} missing_identity={missing_identity}")
        print(f"needs_identity_backfill={needs_backfill}")
        print(f"duplicate_identity_groups={len(duplicate_groups)}")

        for identity, rows in sorted(duplicate_groups.items()):
            survivor = _survivor_listing(rows)
            print(f"[{identity}] canonical_jobs={len({row.job_id for row in rows})}")
            print(
                f"  survivor_job={survivor.job_id} listing={survivor.source_listing_id} "
                f"released={_released_at(survivor)} title={survivor.job.title}"
            )
            for row in rows:
                print(
                    f"  job={row.job_id} listing={row.source_listing_id} "
                    f"status={row.status} released={_released_at(row)} title={row.job.title}"
                )

        if not args.apply:
            print("mode=dry-run; rerun with --apply to backfill identities and merge duplicates")
            return

        # Backfill the explicit key first, including single-listing identities. Future
        # ingestion can then use the same source-backed identity without fuzzy matching.
        for listing in listings:
            identity = stable_identity_from_payload(listing.raw_payload or {})
            if identity is not None:
                listing.raw_payload = with_stable_identity(listing.raw_payload or {}, identity)

        merged_jobs = 0
        reassigned_listings = 0
        for rows in duplicate_groups.values():
            survivor_listing = _survivor_listing(rows)
            survivor_job = survivor_listing.job
            duplicate_ids = {row.job_id for row in rows if row.job_id != survivor_job.id}

            for duplicate_id in sorted(duplicate_ids):
                duplicate = session.get(Job, duplicate_id)
                if duplicate is None or duplicate.id == survivor_job.id:
                    continue
                _merge_missing_job_fields(survivor_job, duplicate)

                attached = list(
                    session.scalars(select(JobListing).where(JobListing.job_id == duplicate.id))
                )
                for listing in attached:
                    listing.job_id = survivor_job.id
                    reassigned_listings += 1

                # Locations on republished copies are expected to describe the same
                # vacancy. Keep the newest survivor's current geography and remove the
                # now-orphan canonical duplicate after all source listings were moved.
                session.flush()
                session.delete(duplicate)
                merged_jobs += 1

        session.commit()
        print(
            f"applied=yes identity_backfilled={needs_backfill} "
            f"merged_jobs={merged_jobs} reassigned_listings={reassigned_listings}"
        )


if __name__ == "__main__":
    main()
