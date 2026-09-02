from __future__ import annotations

import argparse

from sqlalchemy import select

from app.database import SessionLocal
from app.jobs.location_resolution import resolve_localities
from app.models import JobLocation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve existing ungeocoded job location labels with WohnWerk's conservative "
            "locality/area semantics."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum unresolved JobLocation rows to inspect.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what can be resolved without persisting coordinates.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        rows = list(
            session.scalars(
                select(JobLocation)
                .where(
                    JobLocation.location.is_(None),
                    JobLocation.city.is_not(None),
                )
                .order_by(JobLocation.id)
                .limit(max(1, args.limit))
            )
        )
        cities = {row.city for row in rows if row.city}
        resolutions = resolve_localities(session, cities)

        resolved = 0
        for row in rows:
            resolution = resolutions.get(row.city or "")
            if resolution is None:
                continue
            resolved += 1
            print(
                f"location={row.id} job={row.job_id} source={row.location_text!r} "
                f"canonical={resolution.canonical_locality!r} method={resolution.method} "
                f"postal_codes={len(resolution.postal_codes)}"
            )
            if not args.dry_run:
                row.location = resolution.as_wkt()

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    print(f"considered={len(rows)}")
    print(f"resolved={resolved}")
    print(f"committed={not args.dry_run}")


if __name__ == "__main__":
    main()
