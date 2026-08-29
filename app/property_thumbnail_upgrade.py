from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ListingStatus, Property, PropertyListing
from app.property_images import PropertyImage
from app.property_thumbnail_cache import (
    THUMBNAIL_TARGET_WIDTH_PX,
    _ImagePlan,
    _comparison_url,
    _download_image,
    _listing_discovery_url,
    _scan_discovery_page,
)
from app.property_visibility import product_visible_property_condition
from app.version import __version__

THUMBNAIL_QUALITY_POLICY = "search-card-balanced-720-v2"


@dataclass(frozen=True, slots=True)
class ThumbnailUpgradeResult:
    considered: int = 0
    eligible: int = 0
    discovery_pages: int = 0
    discovery_failed: int = 0
    planned: int = 0
    upgraded: int = 0
    unchanged: int = 0
    missing: int = 0
    failed: int = 0


@dataclass(frozen=True, slots=True)
class _UpgradeTarget:
    property_id: int
    listing_id: int
    listing_url: str
    old_filename: str | None
    old_source_image_url: str | None


def _candidate_property_ids(session: Session, *, limit: int) -> list[int]:
    stmt = (
        select(PropertyImage.property_id)
        .join(Property, Property.id == PropertyImage.property_id)
        .where(
            Property.status == ListingStatus.ACTIVE,
            product_visible_property_condition(),
            PropertyImage.status == "cached",
            PropertyImage.local_filename.is_not(None),
        )
        .order_by(PropertyImage.fetched_at.asc().nullsfirst(), PropertyImage.property_id)
        .limit(limit)
    )
    return [int(value) for value in session.scalars(stmt)]


def _active_listing_targets(
    session: Session,
    property_id: int,
    row: PropertyImage,
) -> list[_UpgradeTarget]:
    listings = list(
        session.scalars(
            select(PropertyListing)
            .where(
                PropertyListing.property_id == property_id,
                PropertyListing.status == ListingStatus.ACTIVE,
            )
            .order_by(
                (PropertyListing.id != row.property_listing_id),
                PropertyListing.id,
            )
        )
    )
    output: list[_UpgradeTarget] = []
    seen_pages: set[str] = set()
    for listing in listings:
        page_url = _listing_discovery_url(listing)
        if page_url is None or page_url in seen_pages:
            continue
        seen_pages.add(page_url)
        output.append(
            _UpgradeTarget(
                property_id=property_id,
                listing_id=listing.id,
                listing_url=listing.url,
                old_filename=row.local_filename,
                old_source_image_url=row.source_image_url,
            )
        )
        if len(output) >= 2:
            break
    return output


def _store_balanced_payload(listing: PropertyListing, image_url: str) -> None:
    payload = dict(listing.raw_payload or {})
    payload["thumbnail_url"] = image_url
    payload["thumbnail_semantics"] = THUMBNAIL_QUALITY_POLICY
    payload["thumbnail_target_width_px"] = int(THUMBNAIL_TARGET_WIDTH_PX)
    listing.raw_payload = payload


async def upgrade_cached_property_thumbnails(
    session: Session,
    *,
    limit: int = 500,
    delay_seconds: float = 0.0,
) -> ThumbnailUpgradeResult:
    """Atomically replace cached low-res previews with balanced search-card thumbnails.

    The old local file stays valid until a newly discovered balanced source candidate has
    downloaded successfully. Search/detail lifecycle state is never changed by this pass.
    """
    settings = get_settings()
    property_ids = _candidate_property_ids(session, limit=max(1, limit))
    considered = len(property_ids)

    rows: dict[int, PropertyImage] = {}
    page_targets: dict[str, list[_UpgradeTarget]] = {}
    for property_id in property_ids:
        row = session.scalar(
            select(PropertyImage).where(PropertyImage.property_id == property_id)
        )
        if row is None:
            continue
        rows[property_id] = row
        for target in _active_listing_targets(session, property_id, row):
            listing = session.get(PropertyListing, target.listing_id)
            if listing is None:
                continue
            page_url = _listing_discovery_url(listing)
            if page_url is not None:
                page_targets.setdefault(page_url, []).append(target)

    headers = {
        "User-Agent": f"WohnWerk/{__version__} (+private self-hosted Austrian property search)",
        "Accept": "text/html,image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
    }
    discovery_failed = 0
    plans: dict[int, _ImagePlan] = {}
    selected_targets: dict[int, _UpgradeTarget] = {}
    missing_properties: set[int] = set()
    unchanged = 0

    async with httpx.AsyncClient(
        headers=headers,
        timeout=settings.property_image_timeout_seconds,
        follow_redirects=True,
    ) as client:
        page_semaphore = asyncio.Semaphore(max(1, settings.property_image_discovery_concurrency))
        page_results = await asyncio.gather(
            *(
                _scan_discovery_page(client, page_url, page_semaphore)
                for page_url in page_targets
            )
        )

        for page_url, images, error in page_results:
            if error is not None:
                discovery_failed += 1
                continue
            for target in page_targets.get(page_url, []):
                if target.property_id in plans or target.property_id in missing_properties:
                    continue
                key = _comparison_url(target.listing_url)
                image_url = images.get(key or "")
                if image_url is None:
                    missing_properties.add(target.property_id)
                    continue
                if image_url == target.old_source_image_url:
                    unchanged += 1
                    continue
                plans[target.property_id] = _ImagePlan(
                    property_id=target.property_id,
                    listing_id=target.listing_id,
                    image_url=image_url,
                )
                selected_targets[target.property_id] = target

        download_semaphore = asyncio.Semaphore(max(1, settings.property_image_worker_concurrency))
        download_results = await asyncio.gather(
            *(
                _download_image(
                    client,
                    plan,
                    download_semaphore,
                    max(0.0, delay_seconds),
                )
                for plan in plans.values()
            )
        )

    upgraded = failed = 0
    old_files_to_remove: list[str] = []
    now = datetime.now(UTC)
    for property_id, filename, error in download_results:
        row = rows.get(property_id)
        target = selected_targets.get(property_id)
        plan = plans.get(property_id)
        if row is None or target is None or plan is None:
            failed += 1
            continue
        if error is not None or filename is None:
            failed += 1
            continue

        old_filename = row.local_filename
        row.property_listing_id = plan.listing_id
        row.source_image_url = plan.image_url
        row.local_filename = filename
        row.status = "cached"
        row.retry_after = None
        row.fetched_at = now
        row.updated_at = now
        row.last_error = None

        listing = session.get(PropertyListing, plan.listing_id)
        if listing is not None:
            _store_balanced_payload(listing, plan.image_url)

        if old_filename and old_filename != filename:
            old_files_to_remove.append(old_filename)
        upgraded += 1

    session.commit()

    root = Path(settings.property_image_dir).resolve()
    for filename in old_files_to_remove:
        candidate = (root / filename).resolve()
        if candidate.parent == root:
            candidate.unlink(missing_ok=True)

    eligible = len({target.property_id for targets in page_targets.values() for target in targets})
    return ThumbnailUpgradeResult(
        considered=considered,
        eligible=eligible,
        discovery_pages=len(page_targets),
        discovery_failed=discovery_failed,
        planned=len(plans),
        upgraded=upgraded,
        unchanged=unchanged,
        missing=len(missing_properties),
        failed=failed,
    )
