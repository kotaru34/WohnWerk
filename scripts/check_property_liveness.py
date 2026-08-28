from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.database import SessionLocal
from app.models import ListingStatus, PropertyListing, Source
from app.property_images import PropertyImage
from app.property_liveness import (
    PropertyLivenessSummary,
    _apply_persisted_probe,
    probe_property_urls,
    refresh_immmo_liveness,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify current IMMMO downstream property URLs in small background batches."
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum listings this run.")
    parser.add_argument(
        "--needle",
        help="Only verify an active IMMMO listing whose URL or source ID contains this text.",
    )
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


async def _refresh_target(session, needle: str) -> PropertyLivenessSummary:
    source = session.scalar(select(Source).where(Source.name == "immmo.at"))
    if source is None:
        return PropertyLivenessSummary()

    like = f"%{needle}%"
    listings = list(
        session.scalars(
            select(PropertyListing)
            .where(
                PropertyListing.source_id == source.id,
                PropertyListing.status == ListingStatus.ACTIVE,
                or_(
                    PropertyListing.url.ilike(like),
                    PropertyListing.source_listing_id.ilike(like),
                ),
            )
            .order_by(PropertyListing.id)
        )
    )
    if not listings:
        print(f"target_matches=0 needle={needle}")
        return PropertyLivenessSummary()

    print(f"target_matches={len(listings)} needle={needle}")
    probes = await probe_property_urls([listing.url for listing in listings])
    counts = {"live": 0, "dead": 0, "unknown": 0}
    for listing in listings:
        probe = probes[listing.url]
        counts[probe.state] += 1
        _apply_persisted_probe(listing, probe)
        print(
            f"  listing={listing.id} state={probe.state} status={probe.status_code} "
            f"reason={probe.reason} final_url={probe.final_url}"
        )
    session.commit()
    return PropertyLivenessSummary(
        attempted=len(listings),
        live=counts["live"],
        dead=counts["dead"],
        unknown=counts["unknown"],
    )


async def _run() -> None:
    args = parse_args()
    with SessionLocal() as session:
        if args.needle:
            result = await _refresh_target(session, args.needle)
        else:
            result = await refresh_immmo_liveness(session, limit=args.limit)
        invalidated = _invalidate_dead_listing_images(session)
    print(f"attempted={result.attempted}")
    print(f"live={result.live}")
    print(f"dead={result.dead}")
    print(f"unknown={result.unknown}")
    print(f"invalidated_dead_images={invalidated}")


if __name__ == "__main__":
    asyncio.run(_run())
