from __future__ import annotations

import argparse
import asyncio

from app.database import SessionLocal
from app.property_images import cache_missing_property_images


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cache source-backed preview images for product-visible properties."
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum properties this run.")
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Polite delay between external requests in seconds.",
    )
    return parser.parse_args()


async def _run() -> None:
    args = parse_args()
    with SessionLocal() as session:
        result = await cache_missing_property_images(
            session,
            limit=args.limit,
            delay_seconds=args.delay,
        )
    print(f"attempted={result.attempted}")
    print(f"cached={result.cached}")
    print(f"missing={result.missing}")
    print(f"failed={result.failed}")
    print(f"skipped={result.skipped}")


if __name__ == "__main__":
    asyncio.run(_run())
