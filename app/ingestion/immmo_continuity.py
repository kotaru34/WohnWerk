from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.ingestion.property_continuity import (
    PropertyContinuityMatch,
    PropertyContinuityObservation,
    match_property_continuity,
)
from app.models import (
    CoverageStatus,
    CrawlMode,
    CrawlRun,
    ListingStatus,
    Property,
    PropertyListing,
    Source,
)

CONTINUITY_VERSION = "immmo-continuity-2026-08-28-v3"


@dataclass(frozen=True, slots=True)
class ImmmoContinuityPair:
    previous_listing_id: int
    current_listing_id: int
    strategy: str


@dataclass(frozen=True, slots=True)
class ImmmoContinuitySummary:
    matched: int
    new_rows_reclassified: int
    deleted_properties: int
    strategies: dict[str, int]


def _observation(listing: PropertyListing) -> PropertyContinuityObservation:
    property_row = listing.property
    return PropertyContinuityObservation(
        token=listing.id,
        postal_code=property_row.postal_code,
        title=property_row.title,
        price_eur=property_row.price_eur,
        living_area_m2=property_row.living_area_m2,
    )


def _previous_complete_reconciliation(session: Session, run: CrawlRun) -> CrawlRun | None:
    return session.scalar(
        select(CrawlRun)
        .where(
            CrawlRun.source_id == run.source_id,
            CrawlRun.id != run.id,
            CrawlRun.mode == CrawlMode.RECONCILIATION,
            CrawlRun.coverage_status == CoverageStatus.OK,
            CrawlRun.finished_at.is_not(None),
            CrawlRun.started_at < run.started_at,
        )
        .order_by(CrawlRun.started_at.desc())
        .limit(1)
    )


def find_immmo_continuity_pairs(
    session: Session,
    run: CrawlRun,
) -> list[ImmmoContinuityPair]:
    source = session.get(Source, run.source_id)
    if source is None or source.name != "immmo.at":
        return []
    if run.mode != CrawlMode.RECONCILIATION or run.coverage_status != CoverageStatus.OK:
        return []

    previous_run = _previous_complete_reconciliation(session, run)
    if previous_run is None or previous_run.finished_at is None:
        return []
    continuity_cutoff = previous_run.finished_at

    # Keep the two sides of the comparison stable across repeated repair invocations.
    # A provider-rotation row must have appeared after the previous complete scan and be
    # visible in this one. The historical side must predate that completed scan and be
    # absent now. After a merge the old lifecycle row keeps its original first_seen_at,
    # so it cannot become a new "current" candidate and unlock cascading second-pass
    # matches merely because last_seen_crawl_run_id was updated to this run.
    current = list(
        session.scalars(
            select(PropertyListing)
            .where(
                PropertyListing.source_id == source.id,
                PropertyListing.status == ListingStatus.ACTIVE,
                PropertyListing.last_seen_crawl_run_id == run.id,
                PropertyListing.first_seen_at > continuity_cutoff,
            )
            .order_by(PropertyListing.id)
        )
    )
    previous = list(
        session.scalars(
            select(PropertyListing)
            .where(
                PropertyListing.source_id == source.id,
                PropertyListing.status == ListingStatus.ACTIVE,
                PropertyListing.last_seen_crawl_run_id.is_distinct_from(run.id),
                PropertyListing.first_seen_at <= continuity_cutoff,
                PropertyListing.last_seen_at < run.started_at,
            )
            .order_by(PropertyListing.id)
        )
    )

    matches: list[PropertyContinuityMatch] = match_property_continuity(
        [_observation(listing) for listing in previous],
        [_observation(listing) for listing in current],
    )
    return [
        ImmmoContinuityPair(
            previous_listing_id=int(match.previous_token),
            current_listing_id=int(match.current_token),
            strategy=match.strategy,
        )
        for match in matches
    ]


def _merge_property_metadata(target: Property, current: Property) -> None:
    if current.title:
        target.title = current.title
    if current.description is not None:
        target.description = current.description
    if current.price_eur is not None:
        target.price_eur = current.price_eur
    if current.living_area_m2 is not None:
        target.living_area_m2 = current.living_area_m2
    if current.plot_area_m2 is not None:
        target.plot_area_m2 = current.plot_area_m2
    if current.postal_code is not None:
        target.postal_code = current.postal_code
        target.location = current.location
    if current.city:
        target.city = current.city
    target.first_seen_at = min(target.first_seen_at, current.first_seen_at)
    target.last_seen_at = max(target.last_seen_at, current.last_seen_at)
    target.status = ListingStatus.ACTIVE
    target.inactive_at = None


def _continuity_payload(
    previous: PropertyListing,
    current: PropertyListing,
    *,
    strategy: str,
    now: datetime,
) -> dict:
    previous_payload = dict(previous.raw_payload or {})
    current_payload = dict(current.raw_payload or {})
    merged = dict(previous_payload)
    merged.update(current_payload)

    history = list(previous_payload.get("wohnwerk_url_history") or [])
    if previous.url != current.url:
        history.append(
            {
                "source_listing_id": previous.source_listing_id,
                "url": previous.url,
                "first_seen_at": previous.first_seen_at.isoformat(),
                "last_seen_at": previous.last_seen_at.isoformat(),
            }
        )
    if history:
        merged["wohnwerk_url_history"] = history[-50:]

    old_continuity = previous_payload.get("wohnwerk_continuity")
    rotations = 0
    if isinstance(old_continuity, dict):
        try:
            rotations = int(old_continuity.get("rotations") or 0)
        except (TypeError, ValueError):
            rotations = 0

    merged["wohnwerk_continuity"] = {
        "version": CONTINUITY_VERSION,
        "strategy": strategy,
        "rotations": rotations + 1,
        "matched_at": now.isoformat(),
    }
    return merged


def apply_immmo_continuity_pairs(
    session: Session,
    run: CrawlRun,
    pairs: list[ImmmoContinuityPair],
) -> ImmmoContinuitySummary:
    now = datetime.now(UTC)
    strategies: Counter[str] = Counter()
    new_rows_reclassified = 0
    deleted_properties = 0

    previous_run = _previous_complete_reconciliation(session, run)
    if previous_run is None or previous_run.finished_at is None:
        return ImmmoContinuitySummary(
            matched=0,
            new_rows_reclassified=0,
            deleted_properties=0,
            strategies={},
        )
    continuity_cutoff = previous_run.finished_at

    for pair in pairs:
        previous = session.get(PropertyListing, pair.previous_listing_id)
        current = session.get(PropertyListing, pair.current_listing_id)
        if previous is None or current is None or previous.id == current.id:
            continue
        if previous.source_id != run.source_id or current.source_id != run.source_id:
            continue
        if current.last_seen_crawl_run_id != run.id:
            continue
        if current.first_seen_at <= continuity_cutoff:
            continue
        if previous.last_seen_crawl_run_id == run.id:
            continue
        if previous.first_seen_at > continuity_cutoff:
            continue

        target = previous.property
        current_property = current.property
        _merge_property_metadata(target, current_property)

        current_source_listing_id = current.source_listing_id
        current_url = current.url
        current_payload = _continuity_payload(
            previous,
            current,
            strategy=pair.strategy,
            now=now,
        )
        current_last_seen_at = current.last_seen_at
        current_first_seen_at = current.first_seen_at
        current_run_id = current.last_seen_crawl_run_id
        current_status = current.status

        if run.finished_at is not None and (
            run.started_at <= current_first_seen_at <= run.finished_at
        ):
            new_rows_reclassified += 1

        if current_property.id != target.id:
            attached = list(
                session.scalars(
                    select(PropertyListing).where(
                        PropertyListing.property_id == current_property.id,
                        PropertyListing.id != current.id,
                    )
                )
            )
            for listing in attached:
                listing.property = target

        session.delete(current)
        session.flush()

        previous.source_listing_id = current_source_listing_id
        previous.url = current_url
        previous.status = current_status
        previous.raw_payload = current_payload
        previous.last_seen_crawl_run_id = current_run_id
        previous.first_seen_at = min(previous.first_seen_at, current_first_seen_at)
        previous.last_seen_at = max(previous.last_seen_at, current_last_seen_at)
        previous.inactive_at = None

        if current_property.id != target.id:
            has_listing = session.scalar(
                select(exists().where(PropertyListing.property_id == current_property.id))
            )
            if not has_listing:
                session.delete(current_property)
                deleted_properties += 1

        strategies[pair.strategy] += 1

    session.flush()
    matched = sum(strategies.values())
    metadata = dict(run.run_metadata or {})
    metadata["immmo_continuity"] = {
        "version": CONTINUITY_VERSION,
        "matched": matched,
        "new_rows_reclassified": new_rows_reclassified,
        "deleted_properties": deleted_properties,
        "strategies": dict(sorted(strategies.items())),
        "applied_at": now.isoformat(),
    }
    run.run_metadata = metadata
    session.commit()
    return ImmmoContinuitySummary(
        matched=matched,
        new_rows_reclassified=new_rows_reclassified,
        deleted_properties=deleted_properties,
        strategies=dict(strategies),
    )


def reconcile_immmo_continuity(
    session: Session,
    run: CrawlRun,
) -> ImmmoContinuitySummary:
    pairs = find_immmo_continuity_pairs(session, run)
    return apply_immmo_continuity_pairs(session, run, pairs)
