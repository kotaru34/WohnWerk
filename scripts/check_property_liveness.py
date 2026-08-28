from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.models import PropertyListing
from app.property_images import PropertyImage
from app.property_liveness import refresh_immmo_liveness


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify current IMMMO downstream property URLs in small background batches."
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum listings this run.")
    return parser.parse_args()


def _invalidate_dead_listing_images(session) -> int:
    rows = list(
        session.scalars(
            select(PropertyImage)
            .join(
                PropertyListing,
                PropertyListing.id == PropertyImage.property_listing_id,
            )
            .where(
                PropertyImage.status == "cached",
                PropertyListing.raw_payload.is_not(None),
                PropertyListing.raw_payload["source_liveness_state"].as_string() == "dead",
            )
        )
    )
    now = datetime.now(UTC)
    for row in rows:
        row.status = "pending"
        row.property_listing_id = None
        row.source_image_url = None
        row.local_filename = None
        row.retry_after = None
        row.last_error = "cached image belonged to a confirmed-dead source listing"
        row.updated_at = now
    if rows:
        session.commit()
    return len(rows)


async def _run() -> None:
    args = parse_args()
    with SessionLocal() as session:
        result = await refresh_immmo_liveness(session, limit=args.limit)
        invalidated = _invalidate_dead_listing_images(session)
    print(f"attempted={result.attempted}")
    print(f"live={result.live}")
    print(f"dead={result.dead}")
    print(f"unknown={result.unknown}")
    print(f"invalidated_dead_images={invalidated}")


if __name__ == "__main__":
    asyncio.run(_run())
