from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import CrawlRun, ListingStatus, Property, PropertyListing, Source

REPAIR_VERSION = "immmo-area-semantics-2026-08-28-v1"
SUPPORTED_FORMAT = "immmo-search-discovery-v12"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Clear legacy IMMMO-only canonical living areas that are not backed by "
            "explicit Wohn-/Wohnnutzfläche evidence. Dry-run by default."
        )
    )
    parser.add_argument(
        "--run-id",
        type=int,
        required=True,
        help="Successful full IMMMO v12 reconciliation used as the audit anchor.",
    )
    parser.add_argument("--sample", type=int, default=30)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the repair. Without this flag the command is read-only.",
    )
    return parser.parse_args()


def _decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _validated_run(session, run_id: int) -> tuple[CrawlRun, Source]:
    run = session.get(CrawlRun, run_id)
    if run is None:
        raise SystemExit(f"crawl run not found: {run_id}")
    source = session.get(Source, run.source_id)
    if source is None or source.name != "immmo.at":
        raise SystemExit(f"run {run_id} is not an immmo.at run")
    if run.mode != "reconciliation":
        raise SystemExit(f"run {run_id} is not a reconciliation")
    if run.status != "success" or run.coverage_status != "ok":
        raise SystemExit(
            f"run {run_id} is not a successful complete scan: "
            f"status={run.status} coverage={run.coverage_status}"
        )
    return run, source


def _repair_candidates(session, source: Source) -> list[tuple[Property, PropertyListing]]:
    active_rows = list(
        session.scalars(
            select(PropertyListing)
            .where(
                PropertyListing.source_id == source.id,
                PropertyListing.status == ListingStatus.ACTIVE,
            )
            .order_by(PropertyListing.property_id, PropertyListing.id)
        )
    )

    by_property: dict[int, list[PropertyListing]] = defaultdict(list)
    for row in active_rows:
        payload = row.raw_payload or {}
        if payload.get("format") != SUPPORTED_FORMAT:
            continue
        by_property[row.property_id].append(row)

    if not by_property:
        return []

    property_ids = set(by_property)
    source_counts = {
        int(property_id): int(count)
        for property_id, count in session.execute(
            select(
                PropertyListing.property_id,
                func.count(func.distinct(PropertyListing.source_id)),
            )
            .where(PropertyListing.property_id.in_(property_ids))
            .group_by(PropertyListing.property_id)
        )
    }

    candidates: list[tuple[Property, PropertyListing]] = []
    for property_id, listings in by_property.items():
        if source_counts.get(property_id, 0) != 1:
            continue
        property_row = session.get(Property, property_id)
        if property_row is None or property_row.living_area_m2 is None:
            continue
        if any(
            _decimal((listing.raw_payload or {}).get("explicit_living_area_m2")) is not None
            for listing in listings
        ):
            continue
        # Record one deterministic active listing for audit metadata and samples. The
        # provider-neutral display-area value remains in raw_payload and is not discarded.
        candidates.append((property_row, listings[0]))

    candidates.sort(key=lambda pair: pair[0].id)
    return candidates


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        run, source = _validated_run(session, args.run_id)
        candidates = _repair_candidates(session, source)

        print(f"repair_version={REPAIR_VERSION}")
        print(f"run={run.id} status={run.status} coverage={run.coverage_status}")
        print(f"supported_format={SUPPORTED_FORMAT}")
        print(f"unverified_immmo_only={len(candidates)}")
        print("sample_candidates:")
        for property_row, listing in candidates[: max(0, args.sample)]:
            payload = listing.raw_payload or {}
            print(
                f"  listing={listing.id} property={property_row.id} "
                f"plz={property_row.postal_code or '-'}"
            )
            print(f"    title={property_row.title}")
            print(f"    canonical_living={property_row.living_area_m2}")
            print(f"    display_area={payload.get('display_area_m2')}")
            print(f"    explicit_living={payload.get('explicit_living_area_m2')}")
            print(f"    explicit_plot={payload.get('explicit_plot_area_m2')}")
            print(f"    url={listing.url}")

        if not args.apply:
            print("mode=dry-run no database changes")
            return

        applied_at = datetime.now(UTC).isoformat()
        for property_row, listing in candidates:
            previous = property_row.living_area_m2
            property_row.living_area_m2 = None
            payload = dict(listing.raw_payload or {})
            payload["wohnwerk_area_repair"] = {
                "version": REPAIR_VERSION,
                "run_id": run.id,
                "reason": "legacy_immmo_display_area_not_explicit_living_area",
                "previous_canonical_living_area_m2": str(previous),
                "applied_at": applied_at,
            }
            listing.raw_payload = payload

        session.commit()
        print("mode=apply")
        print(f"canonical_living_cleared={len(candidates)}")


if __name__ == "__main__":
    main()
