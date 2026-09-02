from __future__ import annotations

import argparse
import asyncio

from app.database import SessionLocal
from app.property_thumbnail_cache import (
    cache_property_thumbnails,
    reset_non_cached_image_retries,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cache lightweight source-backed thumbnails for product-visible properties."
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum properties this run.")
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Optional per-download delay in seconds; default is no artificial delay.",
    )
    parser.add_argument(
        "--reset-retry",
        action="store_true",
        help="Retry all non-cached rows immediately (useful after worker logic changes).",
    )
    return parser.parse_args()


async def _run() -> None:
    args = parse_args()
    with SessionLocal() as session:
        if args.reset_retry:
            reset = reset_non_cached_image_retries(session)
            print(f"retry_reset={reset}")
        result = await cache_property_thumbnails(
            session,
            limit=args.limit,
            delay_seconds=args.delay,
        )
    print(f"attempted={result.attempted}")
    print(f"cached={result.cached}")
    print(f"missing={result.missing}")
    print(f"failed={result.failed}")
    print(f"skipped={result.skipped}")
    print(f"known_urls={result.known_urls}")
    print(f"discovered_urls={result.discovered_urls}")
    print(f"discovery_pages={result.discovery_pages}")
    print(f"discovery_failed={result.discovery_failed}")


if __name__ == "__main__":
    asyncio.run(_run())
