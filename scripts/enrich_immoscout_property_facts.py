from __future__ import annotations

import argparse
import asyncio

from app.database import SessionLocal
from app.property_detail_enrichment import enrich_immoscout_property_facts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich supported IMMMO downstream listings with provider-backed property facts."
        )
    )
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument(
        "--needle",
        help="Only inspect IMMMO listing URLs or source IDs containing this token.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate facts without persisting changes.",
    )
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    with SessionLocal() as session:
        summary = await enrich_immoscout_property_facts(
            session,
            limit=args.limit,
            needle=args.needle,
            apply=not args.dry_run,
        )
    for detail in summary.details:
        print(detail)
    print(f"considered={summary.considered}")
    print(f"attempted={summary.attempted}")
    print(f"matched={summary.matched}")
    print(f"missing={summary.missing}")
    print(f"rejected={summary.rejected}")
    print(f"failed={summary.failed}")
    print(f"prices_updated={summary.prices_updated}")
    print(f"plots_updated={summary.plots_updated}")
    print(f"living_updated={summary.living_updated}")
    print(f"usable_updated={summary.usable_updated}")
    print(f"titles_updated={summary.titles_updated}")
    print(f"committed={not args.dry_run}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
