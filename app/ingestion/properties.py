from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.ingestion.listing_identity import stable_external_identity
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
    identity = stable_external_identity(item.url)
    if identity is not None:
        payload["stable_external_identity"] = identity
    return payload


def _merge_listing_payload(existing_payload: dict | None, incoming_payload: dict) -> dict:
    """Merge sparse discovery payloads without discarding prior detail enrichment."""
    existing = dict(existing_payload or {})
    merged = dict(existing)
    merged.update(incoming_payload)

    previous_enriched = existing.get("detail_enriched") is True
    incoming_enriched = incoming_payload.get("detail_enriched")

    if previous_enriched and incoming_enriched is not True:
        merged["detail_enriched"] = True
        transient_error = incoming_payload.get("detail_enrichment_error")
        if transient_error:
            merged["detail_enrichment_last_error"] = transient_error
        merged.pop("detail_enrichment_error", None)
    elif incoming_enriched is True:
        merged.pop("detail_enrichment_error", None)
        merged.pop("detail_enrichment_last_error", None)

    return merged


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


def _stable_identity_candidates(
    session: Session,
    identities: set[str],
) -> dict[str, Property]:
    """Resolve known provider-issued IDs to the oldest existing canonical property."""
    if not identities:
        return {}

    # At present the only supported provider identity is sreal.at:<object-id>.
    # Keep this query deliberately narrow rather than scanning every listing URL.
    rows = session.scalars(
        select(PropertyListing)
        .where(PropertyListing.url.ilike("%sreal.at/%"))
        .order_by(PropertyListing.id)
    )
    resolved: dict[str, Property] = {}
    for listing in rows:
        identity = stable_external_identity(listing.url)
        if identity in identities:
            resolved.setdefault(identity, listing.property)
    return resolved


def _delete_orphan_properties(session: Session, property_ids: set[int]) -> None:
    if not property_ids:
        return
    session.flush()
    for property_id in property_ids:
        has_listing = session.scalar(
            select(
                exists().where(PropertyListing.property_id == property_id)
            )
        )
        if has_listing:
            continue
        property_row = session.get(Property, property_id)
        if property_row is not None:
            session.delete(property_row)


def ingest_properties(
    session: Session,
    *,
    source: Source,
    run: CrawlRun,
    items: list[RawProperty],
) -> tuple[int, int]:
    """Persist property discovery with deterministic cross-source deduplication.

    Sparse discovery updates are enrichment-only. Cross-source identity is reused when
    either the canonical URL is exactly equal or a provider exposes an unambiguous stable
    object ID (currently s REAL detail IDs). Fuzzy/content deduplication remains a separate
    later stage and is never guessed here.
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

    incoming_identities = {
        identity
        for item in items
        if (identity := stable_external_identity(item.url)) is not None
    }
    stable_identity_properties = _stable_identity_candidates(session, incoming_identities)

    new_count = 0
    updated_count = 0
    orphan_candidates: set[int] = set()

    for item in items:
        postal = known_postal.get(item.postal_code or "")
        listing = existing.get(item.source_listing_id)
        payload = _listing_payload(item, postal_resolved=postal is not None)
        stable_identity = stable_external_identity(item.url)

        if listing is None:
            property_row = exact_url_properties.get(item.url)
            if property_row is None and stable_identity is not None:
                property_row = stable_identity_properties.get(stable_identity)

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
            else:
                _enrich_property(property_row, item=item, postal=postal, now=now)

            exact_url_properties[item.url] = property_row
            if stable_identity is not None:
                stable_identity_properties.setdefault(stable_identity, property_row)

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
        if stable_identity is not None:
            target = stable_identity_properties.get(stable_identity)
            if target is not None and target.id != property_row.id:
                orphan_candidates.add(property_row.id)
                listing.property = target
                property_row = target

        _enrich_property(property_row, item=item, postal=postal, now=now)

        listing.url = item.url
        listing.status = ListingStatus.ACTIVE
        listing.raw_payload = _merge_listing_payload(listing.raw_payload, payload)
        listing.last_seen_crawl_run_id = run.id
        listing.last_seen_at = now
        listing.inactive_at = None
        exact_url_properties[item.url] = property_row
        if stable_identity is not None:
            stable_identity_properties[stable_identity] = property_row
        updated_count += 1

    _delete_orphan_properties(session, orphan_candidates)
    session.commit()
    return new_count, updated_count
