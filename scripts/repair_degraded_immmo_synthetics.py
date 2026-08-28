from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import exists, select, update

from app.database import SessionLocal
from app.models import (
    CoverageStatus,
    CrawlMode,
    CrawlRun,
    ListingStatus,
    Property,
    PropertyListing,
    Source,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Deactivate synthetic IMMMO rows introduced only by one degraded reconciliation "
            "after a later complete reconciliation confirms they were parser fallout."
        )
    )
    parser.add_argument("--bad-run", type=int, required=True)
    parser.add_argument("--confirm-run", type=int, required=True)
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _run(session, run_id: int) -> CrawlRun:
    run = session.get(CrawlRun, run_id)
    if run is None:
        raise SystemExit(f"crawl run {run_id} not found")
    return run


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        bad = _run(session, args.bad_run)
        confirm = _run(session, args.confirm_run)
        source = session.get(Source, bad.source_id)

        if source is None or source.name != "immmo.at":
            raise SystemExit("bad run is not an IMMMO run")
        if confirm.source_id != bad.source_id:
            raise SystemExit("confirmation run belongs to another source")
        if bad.mode != CrawlMode.RECONCILIATION or bad.coverage_status == CoverageStatus.OK:
            raise SystemExit("bad run must be a non-OK reconciliation")
        if (
            confirm.mode != CrawlMode.RECONCILIATION
            or confirm.coverage_status != CoverageStatus.OK
            or confirm.started_at <= bad.started_at
        ):
            raise SystemExit("confirmation run must be a later coverage=ok reconciliation")
        if bad.finished_at is None:
            raise SystemExit("bad run has no finished_at")

        candidates = list(
            session.scalars(
                select(PropertyListing)
                .where(
                    PropertyListing.source_id == bad.source_id,
                    PropertyListing.status == ListingStatus.ACTIVE,
                    PropertyListing.first_seen_at >= bad.started_at,
                    PropertyListing.first_seen_at <= bad.finished_at,
                    PropertyListing.last_seen_crawl_run_id == bad.id,
                    PropertyListing.raw_payload.op("->>")("original_url_missing") == "true",
                )
                .order_by(PropertyListing.id)
            )
        )

        print(f"bad_run={bad.id} coverage={bad.coverage_status}")
        print(f"confirm_run={confirm.id} coverage={confirm.coverage_status}")
        print(f"candidates={len(candidates)}")
        print("sample:")
        for listing in candidates[: max(0, args.sample)]:
            prop = session.get(Property, listing.property_id)
            print(
                f"  listing={listing.id} property={listing.property_id} "
                f"price={prop.price_eur if prop else None} "
                f"title={(prop.title if prop else '')[:120]!r} url={listing.url}"
            )

        if not args.apply:
            print("mode=dry-run no database changes")
            return

        now = datetime.now(UTC)
        candidate_ids = [listing.id for listing in candidates]
        property_ids = {listing.property_id for listing in candidates}
        if candidate_ids:
            session.execute(
                update(PropertyListing)
                .where(PropertyListing.id.in_(candidate_ids))
                .values(status=ListingStatus.INACTIVE, inactive_at=now)
            )

        active_listing = exists(
            select(PropertyListing.id).where(
                PropertyListing.property_id == Property.id,
                PropertyListing.status == ListingStatus.ACTIVE,
            )
        )
        if property_ids:
            session.execute(
                update(Property)
                .where(
                    Property.id.in_(property_ids),
                    Property.status == ListingStatus.ACTIVE,
                    ~active_listing,
                )
                .values(status=ListingStatus.INACTIVE, inactive_at=now)
            )

        session.commit()
        print(f"deactivated_listings={len(candidate_ids)}")
        print("mode=applied")


if __name__ == "__main__":
    main()
