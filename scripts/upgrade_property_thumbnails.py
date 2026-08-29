from __future__ import annotations

import argparse
import asyncio

from app.database import SessionLocal
from app.property_thumbnail_upgrade import upgrade_cached_property_thumbnails


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Atomically replace already-cached low-resolution property previews with "
            "balanced ~720px search-card thumbnails."
        )
    )
    parser.add_argument("--limit", type=int, default=500, help="Maximum cached properties this run.")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Optional per-download delay in seconds; default is no artificial delay.",
    )
    return parser.parse_args()


async def _run() -> None:
    args = parse_args()
    with SessionLocal() as session:
        result = await upgrade_cached_property_thumbnails(
            session,
            limit=max(1, args.limit),
            delay_seconds=max(0.0, args.delay),
        )

    print(f"considered={result.considered}")
    print(f"eligible={result.eligible}")
    print(f"discovery_pages={result.discovery_pages}")
    print(f"discovery_failed={result.discovery_failed}")
    print(f"planned={result.planned}")
    print(f"upgraded={result.upgraded}")
    print(f"unchanged={result.unchanged}")
    print(f"missing={result.missing}")
    print(f"failed={result.failed}")


if __name__ == "__main__":
    asyncio.run(_run())
