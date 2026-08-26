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


def _listing_payload(item: RawProperty, *, postal_resolved: bool) -> dict:
    payload = dict(item.raw_payload)
    payload["source_postal_code"] = item.postal_code
    payload["postal_code_resolved"] = postal_resolved
    return payload


def _enrich_property(
    property_row: Property,
    *,
    item: RawProperty,
    postal: PostalCode | None,
    now: datetime,
) -> None:
    """Apply non-null source metadata without degrading already-known fields."""
    if item.title:
        property_row.title = item.title
    if item.description is not None:
        property_row.description = item.description
    if item.price_eur is not None:
        property_row.price_eur = item.price_eur
    if item.living_area_m2 is not None:
        property_row.living_area_m2 = item.living_area_m2
    if item.plot_area_m2 is not None:
        property_row.plot_area_m2 = item.plot_area_m2
    if postal is not None:
        property_row.postal_code = postal.postal_code
        property_row.location = postal.location
    if item.city:
        property_row.city = item.city
    property_row.status = ListingStatus.ACTIVE
    property_row.last_seen_at = now
    property_row.inactive_at = None


def ingest_properties(
    session: Session,
    *,
    source: Source,
    run: CrawlRun,
    items: list[RawProperty],
) -> tuple[int, int]:
    """Persist a property batch with only deterministic cross-source deduplication.

    Sparse discovery updates are enrichment-only. Cross-source identity is reused only
    when the canonical listing URL is exactly equal; fuzzy/content deduplication is a
    separate later stage and must not be guessed here.
    """
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

    urls = {item.url for item in items}
    exact_url_properties: dict[str, Property] = {}
    if urls:
        for listing in session.scalars(
            select(PropertyListing)
            .where(PropertyListing.url.in_(urls))
            .order_by(PropertyListing.id)
        ):
            exact_url_properties.setdefault(listing.url, listing.property)

    new_count = 0
    updated_count = 0

    for item in items:
        postal = known_postal.get(item.postal_code or "")
        listing = existing.get(item.source_listing_id)
        payload = _listing_payload(item, postal_resolved=postal is not None)

        if listing is None:
            property_row = exact_url_properties.get(item.url)
            if property_row is None:
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
                exact_url_properties[item.url] = property_row
            else:
                _enrich_property(property_row, item=item, postal=postal, now=now)

            listing = PropertyListing(
                property_id=property_row.id,
                source_id=source.id,
                source_listing_id=item.source_listing_id,
                url=item.url,
                status=ListingStatus.ACTIVE,
                raw_payload=payload,
                last_seen_crawl_run_id=run.id,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(listing)
            existing[item.source_listing_id] = listing
            new_count += 1
            continue

        property_row = listing.property
        _enrich_property(property_row, item=item, postal=postal, now=now)

        listing.url = item.url
        listing.status = ListingStatus.ACTIVE
        listing.raw_payload = payload
        listing.last_seen_crawl_run_id = run.id
        listing.last_seen_at = now
        listing.inactive_at = None
        exact_url_properties.setdefault(item.url, property_row)
        updated_count += 1

    session.commit()
    return new_count, updated_count
