from __future__ import annotations

import argparse
from collections import Counter

from app.database import SessionLocal
from app.ingestion.immmo_continuity import (
    CONTINUITY_VERSION,
    apply_immmo_continuity_pairs,
    find_immmo_continuity_pairs,
)
from app.models import CoverageStatus, CrawlMode, CrawlRun, PropertyListing, Source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Repair IMMMO provider-URL churn by merging only deterministic one-to-one "
            "continuity matches from one complete reconciliation run."
        )
    )
    parser.add_argument("--run-id", type=int, required=True, help="Complete IMMMO reconciliation run ID.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the deterministic repair. Without this flag the command is read-only.",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=20,
        help="Number of matched pairs to print (default: 20).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        run = session.get(CrawlRun, args.run_id)
        if run is None:
            raise SystemExit(f"crawl run not found: {args.run_id}")
        source = session.get(Source, run.source_id)
        if source is None or source.name != "immmo.at":
            raise SystemExit(f"run {args.run_id} is not an immmo.at run")
        if run.mode != CrawlMode.RECONCILIATION:
            raise SystemExit(f"run {args.run_id} is not a reconciliation run")
        if run.coverage_status != CoverageStatus.OK:
            raise SystemExit(
                f"run {args.run_id} does not have coverage=ok: {run.coverage_status}"
            )

        pairs = find_immmo_continuity_pairs(session, run)
        strategies = Counter(pair.strategy for pair in pairs)

        print(f"continuity_version={CONTINUITY_VERSION}")
        print(f"run={run.id} status={run.status} coverage={run.coverage_status}")
        print(f"deterministic_pairs={len(pairs)}")
        print(
            "strategies="
            + (",".join(f"{key}:{value}" for key, value in sorted(strategies.items())) or "-")
        )
        print("sample_pairs:")
        for pair in pairs[: max(0, args.sample)]:
            previous = session.get(PropertyListing, pair.previous_listing_id)
            current = session.get(PropertyListing, pair.current_listing_id)
            if previous is None or current is None:
                continue
            property_row = current.property
            print(
                f"  strategy={pair.strategy} previous_listing={previous.id} "
                f"current_listing={current.id} property={property_row.id} "
                f"plz={property_row.postal_code or '-'}"
            )
            print(f"    title={property_row.title}")
            print(f"    previous_url={previous.url}")
            print(f"    current_url={current.url}")

        if not args.apply:
            print("mode=dry-run no database changes")
            return

        summary = apply_immmo_continuity_pairs(session, run, pairs)
        print("mode=apply")
        print(f"matched={summary.matched}")
        print(f"new_rows_reclassified={summary.new_rows_reclassified}")
        print(f"deleted_properties={summary.deleted_properties}")
        print(
            "applied_strategies="
            + (
                ",".join(
                    f"{key}:{value}" for key, value in sorted(summary.strategies.items())
                )
                or "-"
            )
        )


if __name__ == "__main__":
    main()
