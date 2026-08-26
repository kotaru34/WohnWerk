from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CrawlRun,
    ListingStatus,
    PostalCode,
    Property,
    PropertyListing,
    Source,
)
from app.sources.base import RawProperty


def ingest_properties(
    session: Session,
    *,
    source: Source,
    run: CrawlRun,
    items: list[RawProperty],
) -> tuple[int, int]:
    """Persist a property batch without making unsafe cross-source dedup guesses."""
    if not items:
        return 0, 0

    now = datetime.now(UTC)
    postal_codes = {item.postal_code for item in items if item.postal_code}
    known_postal = {
        row.postal_code: row
        for row in session.scalars(
            select(PostalCode).where(PostalCode.postal_code.in_(postal_codes))
        )
    }
    source_ids = [item.source_listing_id for item in items]
    existing = {
        listing.source_listing_id: listing
        for listing in session.scalars(
            select(PropertyListing).where(
                PropertyListing.source_id == source.id,
                PropertyListing.source_listing_id.in_(source_ids),
            )
        )
    }

    new_count = 0
    updated_count = 0

    for item in items:
        postal = known_postal.get(item.postal_code or "")
        listing = existing.get(item.source_listing_id)

        if listing is None:
            property_row = Property(
                title=item.title,
                description=item.description,
                price_eur=item.price_eur,
                living_area_m2=item.living_area_m2,
                plot_area_m2=item.plot_area_m2,
                postal_code=postal.postal_code if postal else None,
                city=item.city,
                location=postal.location if postal else None,
                status=ListingStatus.ACTIVE,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(property_row)
            session.flush()
            listing = PropertyListing(
                property_id=property_row.id,
                source_id=source.id,
                source_listing_id=item.source_listing_id,
                url=item.url,
                status=ListingStatus.ACTIVE,
                raw_payload=item.raw_payload,
                last_seen_crawl_run_id=run.id,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(listing)
            new_count += 1
            continue

        property_row = listing.property
        property_row.title = item.title
        property_row.description = item.description
        property_row.price_eur = item.price_eur
        property_row.living_area_m2 = item.living_area_m2
        property_row.plot_area_m2 = item.plot_area_m2
        property_row.postal_code = postal.postal_code if postal else None
        property_row.city = item.city
        property_row.location = postal.location if postal else None
        property_row.status = ListingStatus.ACTIVE
        property_row.last_seen_at = now
        property_row.inactive_at = None

        listing.url = item.url
        listing.status = ListingStatus.ACTIVE
        listing.raw_payload = item.raw_payload
        listing.last_seen_crawl_run_id = run.id
        listing.last_seen_at = now
        listing.inactive_at = None
        updated_count += 1

    session.commit()
    return new_count, updated_count
