from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from app.database import SessionLocal
from app.property_heating_enrichment import (
    DEFAULT_SOURCE_NAMES,
    enrich_active_property_heating,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich active German house listings with source-backed heating facts."
    )
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        help=(
            "Supported source name. Repeat to select multiple. "
            f"Default: {', '.join(DEFAULT_SOURCE_NAMES)}"
        ),
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--refresh-after-hours", type=float, default=168.0)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    if args.limit <= 0:
        raise SystemExit("--limit must be positive")
    if args.refresh_after_hours < 0:
        raise SystemExit("--refresh-after-hours must be non-negative")

    with SessionLocal() as session:
        stats = await enrich_active_property_heating(
            session,
            source_names=args.sources or DEFAULT_SOURCE_NAMES,
            limit=args.limit,
            delay_seconds=max(2.0, args.delay),
            refresh_after=timedelta(hours=args.refresh_after_hours),
        )

    print(
        f"considered={stats.considered} fetched={stats.fetched} "
        f"found={stats.found} unknown={stats.unknown} failed={stats.failed}"
    )
    return 0 if stats.failed < stats.considered or stats.considered == 0 else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
