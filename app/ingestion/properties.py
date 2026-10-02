from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.ingestion.listing_identity import stable_external_identity
from app.ingestion.property_continuity import (
    PropertyContinuityObservation,
    continuity_area_m2,
    match_property_continuity,
)
from app.models import (
    CrawlRun,
    ListingStatus,
    PostalCode,
    Property,
    PropertyListing,
    Source,
)
from app.property_dedupe import cross_source_duplicate_strategy
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
        if property_row.location_method in {None, "postal_place_mean", "address_mean"}:
            property_row.location = postal.location
            property_row.location_source = postal.location_source
            property_row.location_method = postal.location_method
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


def _immmo_continuity_candidates(
    session: Session,
    *,
    source: Source,
    run: CrawlRun,
    items: list[RawProperty],
    existing_ids: set[str],
) -> dict[str, tuple[PropertyListing, str]]:
    """Reconnect IMMMO cards when the meta-search rotates their downstream provider URL.

    This optimization is intentionally restricted to complete reconciliation scans. During
    an incremental first-pages scan, an active older listing that is merely deeper in the
    result set is not evidence of provider rotation and must never be merged away.
    """
    if source.name != "immmo.at" or run.mode != "reconciliation":
        return {}

    unknown_items = [
        item
        for item in items
        if item.source_listing_id not in existing_ids and item.postal_code
    ]
    if not unknown_items:
        return {}

    postal_codes = {item.postal_code for item in unknown_items if item.postal_code}
    incoming_ids = {item.source_listing_id for item in items}
    candidates = list(
        session.scalars(
            select(PropertyListing)
            .join(Property, Property.id == PropertyListing.property_id)
            .where(
                PropertyListing.source_id == source.id,
                PropertyListing.status == ListingStatus.ACTIVE,
                PropertyListing.last_seen_crawl_run_id.is_distinct_from(run.id),
                PropertyListing.source_listing_id.notin_(incoming_ids),
                Property.postal_code.in_(postal_codes),
            )
            .order_by(PropertyListing.id)
        )
    )
    if not candidates:
        return {}

    previous = [
        PropertyContinuityObservation(
            token=listing.id,
            postal_code=listing.property.postal_code,
            title=listing.property.title,
            price_eur=listing.property.price_eur,
            living_area_m2=continuity_area_m2(
                listing.raw_payload,
                listing.property.living_area_m2,
            ),
        )
        for listing in candidates
    ]
    current = [
        PropertyContinuityObservation(
            token=item.source_listing_id,
            postal_code=item.postal_code,
            title=item.title,
            price_eur=item.price_eur,
            living_area_m2=continuity_area_m2(item.raw_payload, item.living_area_m2),
        )
        for item in unknown_items
    ]
    candidates_by_id = {listing.id: listing for listing in candidates}

    result: dict[str, tuple[PropertyListing, str]] = {}
    for match in match_property_continuity(previous, current):
        listing = candidates_by_id.get(int(match.previous_token))
        if listing is None:
            continue
        result[str(match.current_token)] = (listing, match.strategy)
    return result


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
    either the canonical URL is exactly equal, a provider exposes an unambiguous stable
    object ID (currently s REAL detail IDs), or a single cross-source candidate satisfies
    the conservative PLZ/price/area/title evidence policy. IMMMO additionally gets
    one-to-one continuity matching during complete scans because its meta-search may rotate
    the downstream portal for the same house. Ambiguous fuzzy candidates are never merged.
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
    continuity_candidates = _immmo_continuity_candidates(
        session,
        source=source,
        run=run,
        items=items,
        existing_ids=set(existing),
    )

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

    cross_candidates_by_postal: dict[str, list[Property]] = defaultdict(list)
    cross_candidate_source_ids: dict[int, set[int]] = defaultdict(set)
    if postal_codes:
        cross_candidates = list(
            session.scalars(
                select(Property)
                .where(
                    Property.postal_code.in_(postal_codes),
                    Property.status == ListingStatus.ACTIVE,
                )
                .order_by(Property.id)
            )
        )
        candidate_ids = {candidate.id for candidate in cross_candidates}
        for candidate in cross_candidates:
            if candidate.postal_code:
                cross_candidates_by_postal[candidate.postal_code].append(candidate)
        if candidate_ids:
            for property_id, source_id in session.execute(
                select(PropertyListing.property_id, PropertyListing.source_id).where(
                    PropertyListing.property_id.in_(candidate_ids),
                    PropertyListing.status == ListingStatus.ACTIVE,
                )
            ):
                cross_candidate_source_ids[int(property_id)].add(int(source_id))

    new_count = 0
    updated_count = 0
    orphan_candidates: set[int] = set()

    for item in items:
        postal = known_postal.get(item.postal_code or "")
        listing = existing.get(item.source_listing_id)
        payload = _listing_payload(item, postal_resolved=postal is not None)

        if listing is None:
            continuity = continuity_candidates.get(item.source_listing_id)
            if continuity is not None:
                listing, strategy = continuity
                previous_source_listing_id = listing.source_listing_id
                previous_url = listing.url
                listing.source_listing_id = item.source_listing_id
                existing.pop(previous_source_listing_id, None)
                existing[item.source_listing_id] = listing
                payload["wohnwerk_continuity"] = {
                    "strategy": strategy,
                    "previous_source_listing_id": previous_source_listing_id,
                    "previous_url": previous_url,
                    "matched_at": now.isoformat(),
                }

        stable_identity = stable_external_identity(item.url)

        if listing is None:
            property_row = exact_url_properties.get(item.url)
            if property_row is None and stable_identity is not None:
                property_row = stable_identity_properties.get(stable_identity)

            if property_row is None and item.postal_code:
                matches: list[tuple[Property, str]] = []
                for candidate in cross_candidates_by_postal.get(item.postal_code, []):
                    # A source publishing two ads with similar facts is not cross-source
                    # syndication evidence. Only candidates backed by other sources qualify.
                    if source.id in cross_candidate_source_ids.get(candidate.id, set()):
                        continue
                    strategy = cross_source_duplicate_strategy(
                        candidate,
                        postal_code=item.postal_code,
                        price_eur=item.price_eur,
                        title=item.title,
                        living_area_m2=item.living_area_m2,
                        plot_area_m2=item.plot_area_m2,
                    )
                    if strategy is not None:
                        matches.append((candidate, strategy))

                if len(matches) == 1:
                    property_row, strategy = matches[0]
                    payload["wohnwerk_dedupe"] = {
                        "strategy": strategy,
                        "matched_property_id": property_row.id,
                        "matched_at": now.isoformat(),
                    }

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
                    location_source=postal.location_source if postal else None,
                    location_method=postal.location_method if postal else None,
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
