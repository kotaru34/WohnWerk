from __future__ import annotations

import argparse
import asyncio

from app.database import SessionLocal
from app.property_liveness import refresh_immmo_liveness


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify current IMMMO downstream property URLs in small background batches."
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum listings this run.")
    return parser.parse_args()


async def _run() -> None:
    args = parse_args()
    with SessionLocal() as session:
        result = await refresh_immmo_liveness(session, limit=args.limit)
    print(f"attempted={result.attempted}")
    print(f"live={result.live}")
    print(f"dead={result.dead}")
    print(f"unknown={result.unknown}")


if __name__ == "__main__":
    asyncio.run(_run())
