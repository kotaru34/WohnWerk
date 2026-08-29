from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

import httpx
from sqlalchemy import or_, select

from app.config import get_settings
from app.database import SessionLocal
from app.models import ListingStatus, PropertyListing
from app.property_thumbnail_cache import _cache_row, _download_image, _ImagePlan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh a property thumbnail from provider detail metadata already stored "
            "as primary_image_url."
        )
    )
    parser.add_argument(
        "--needle",
        required=True,
        help="Substring of the listing URL or source listing ID.",
    )
    return parser.parse_args()


async def _run() -> None:
    args = parse_args()
    settings = get_settings()
    needle = args.needle.strip()
    like = f"%{needle}%"

    with SessionLocal() as session:
        listings = list(
            session.scalars(
                select(PropertyListing)
                .where(
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
            raise SystemExit(f"target_matches=0 needle={needle}")

        plans: list[tuple[PropertyListing, _ImagePlan]] = []
        seen_properties: set[int] = set()
        for listing in listings:
            if listing.property_id in seen_properties:
                continue
            seen_properties.add(listing.property_id)
            payload = listing.raw_payload or {}
            image_url = payload.get("primary_image_url")
            if not isinstance(image_url, str) or not image_url.strip():
                print(
                    f"listing={listing.id} property={listing.property_id} "
                    "primary_image_url=missing"
                )
                continue
            plans.append(
                (
                    listing,
                    _ImagePlan(
                        property_id=listing.property_id,
                        listing_id=listing.id,
                        image_url=image_url.strip(),
                    ),
                )
            )

        if not plans:
            raise SystemExit(
                "No target has primary_image_url; run detail enrichment for the listing first."
            )

        headers = {
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian property search)",
            "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
        }
        async with httpx.AsyncClient(
            headers=headers,
            timeout=settings.property_image_timeout_seconds,
            follow_redirects=True,
        ) as client:
            results = await asyncio.gather(
                *(
                    _download_image(client, plan, asyncio.Semaphore(1), 0.0)
                    for _listing, plan in plans
                )
            )

        refreshed = 0
        for (listing, plan), (property_id, filename, error) in zip(
            plans, results, strict=True
        ):
            if filename is None:
                print(
                    f"listing={listing.id} property={property_id} refresh=failed error={error}"
                )
                continue
            row = _cache_row(session, property_id)
            now = datetime.now(UTC)
            row.property_listing_id = listing.id
            row.source_image_url = plan.image_url
            row.local_filename = filename
            row.status = "cached"
            row.retry_after = None
            row.fetched_at = now
            row.last_attempt_at = now
            row.updated_at = now
            row.last_error = None
            refreshed += 1
            print(
                f"listing={listing.id} property={property_id} refresh=cached "
                f"image={plan.image_url} file={filename}"
            )

        session.commit()
        print(f"refreshed={refreshed}")


if __name__ == "__main__":
    asyncio.run(_run())
