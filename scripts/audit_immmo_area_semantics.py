from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import CrawlRun, PropertyListing, Source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit IMMMO v10 display-area semantics after a crawl without changing data."
        )
    )
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--sample", type=int, default=30)
    return parser.parse_args()


def _decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _close(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return False
    tolerance = max(Decimal("1"), max(abs(left), abs(right)) * Decimal("0.01"))
    return abs(left - right) <= tolerance


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        run = session.get(CrawlRun, args.run_id)
        if run is None:
            raise SystemExit(f"crawl run not found: {args.run_id}")
        source = session.get(Source, run.source_id)
        if source is None or source.name != "immmo.at":
            raise SystemExit(f"run {args.run_id} is not an immmo.at run")

        rows = list(
            session.scalars(
                select(PropertyListing)
                .where(
                    PropertyListing.source_id == source.id,
                    PropertyListing.last_seen_crawl_run_id == run.id,
                )
                .order_by(PropertyListing.id)
            )
        )
        property_ids = {row.property_id for row in rows}
        source_counts = {
            property_id: int(count)
            for property_id, count in session.execute(
                select(
                    PropertyListing.property_id,
                    func.count(func.distinct(PropertyListing.source_id)),
                )
                .where(PropertyListing.property_id.in_(property_ids))
                .group_by(PropertyListing.property_id)
            )
        }

        formats: Counter[str] = Counter()
        semantics: Counter[str] = Counter()
        explicit_living = 0
        explicit_plot = 0
        suspicious_plot_as_living: list[PropertyListing] = []
        canonical_living_mismatch: list[PropertyListing] = []

        for row in rows:
            payload = row.raw_payload or {}
            formats[str(payload.get("format") or "-")] += 1
            semantics[str(payload.get("display_area_semantics") or "-")] += 1

            living = _decimal(payload.get("explicit_living_area_m2"))
            plot = _decimal(payload.get("explicit_plot_area_m2"))
            canonical_living = row.property.living_area_m2

            if living is not None:
                explicit_living += 1
                if canonical_living is not None and not _close(canonical_living, living):
                    canonical_living_mismatch.append(row)
            if plot is not None:
                explicit_plot += 1

            if (
                living is None
                and plot is not None
                and canonical_living is not None
                and _close(canonical_living, plot)
            ):
                suspicious_plot_as_living.append(row)

        safe_cleanup = [
            row
            for row in suspicious_plot_as_living
            if source_counts.get(row.property_id, 0) == 1
        ]

        print(f"run={run.id} status={run.status} coverage={run.coverage_status}")
        print(f"rows_seen={len(rows)}")
        print("formats=" + ",".join(f"{k}:{v}" for k, v in sorted(formats.items())))
        print("semantics=" + ",".join(f"{k}:{v}" for k, v in sorted(semantics.items())))
        print(f"explicit_living={explicit_living}")
        print(f"explicit_plot={explicit_plot}")
        print(f"canonical_living_mismatch={len(canonical_living_mismatch)}")
        print(f"suspicious_plot_as_living={len(suspicious_plot_as_living)}")
        print(f"suspicious_immmo_only={len(safe_cleanup)}")

        print("sample_suspicious_immmo_only:")
        for row in safe_cleanup[: max(0, args.sample)]:
            payload = row.raw_payload or {}
            print(
                f"  listing={row.id} property={row.property_id} "
                f"plz={row.property.postal_code or '-'} "
                f"semantic={payload.get('display_area_semantics') or '-'}"
            )
            print(f"    title={row.property.title}")
            print(f"    canonical_living={row.property.living_area_m2}")
            print(f"    display_area={payload.get('display_area_m2')}")
            print(f"    explicit_living={payload.get('explicit_living_area_m2')}")
            print(f"    explicit_plot={payload.get('explicit_plot_area_m2')}")
            print(f"    url={row.url}")

        print("mode=read-only no database changes")


if __name__ == "__main__":
    main()
