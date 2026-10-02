from __future__ import annotations

import argparse
import asyncio

from app.database import SessionLocal
from app.internet_source_enrichment import enrich_de_internet_source_evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch a bounded set of active Immowelt DE detail pages and persist "
            "source-backed Internet evidence."
        )
    )
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and parse evidence without writing database changes.",
    )
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    with SessionLocal() as session:
        summary = await enrich_de_internet_source_evidence(
            session,
            limit=max(1, args.limit),
            apply=not args.dry_run,
        )
    for detail in summary.details:
        print(detail)
    print(f"considered={summary.considered}")
    print(f"attempted={summary.attempted}")
    print(f"matched={summary.matched}")
    print(f"missing={summary.missing}")
    print(f"challenged={summary.challenged}")
    print(f"failed={summary.failed}")
    print(f"evidence_rows={summary.evidence_rows}")
    print(f"halted={summary.halted}")
    print(f"committed={not args.dry_run}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
