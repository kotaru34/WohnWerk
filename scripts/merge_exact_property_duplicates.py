from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select

from app.candidate_activity import CandidatePropertyPreference
from app.database import SessionLocal
from app.models import ListingStatus, Property, PropertyListing, Source
from app.property_dedupe import (
    PropertyDuplicateKey,
    properties_have_compatible_duplicate_facts,
    property_duplicate_key,
)
from app.property_images import PropertyImage

_SOURCE_NAMES = {"immmo.at", "sreal.at"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge only high-confidence active sREAL/IMMMO syndicated property duplicates "
            "with equal normalized title, PLZ and exact price."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the displayed deterministic merges. Default is read-only.",
    )
    parser.add_argument(
        "--needle",
        help="Optional case-insensitive title/URL substring to restrict the repair.",
    )
    return parser.parse_args()


def _merge_metadata(target: Property, duplicate: Property) -> None:
    """Preserve direct sREAL metadata and fill only fields it does not know."""
    if not target.title and duplicate.title:
        target.title = duplicate.title
    if target.description is None and duplicate.description is not None:
        target.description = duplicate.description
    if target.price_eur is None and duplicate.price_eur is not None:
        target.price_eur = duplicate.price_eur
    if target.living_area_m2 is None and duplicate.living_area_m2 is not None:
        target.living_area_m2 = duplicate.living_area_m2
    if target.plot_area_m2 is None and duplicate.plot_area_m2 is not None:
        target.plot_area_m2 = duplicate.plot_area_m2
    if target.postal_code is None and duplicate.postal_code is not None:
        target.postal_code = duplicate.postal_code
        target.location = duplicate.location
    if target.city is None and duplicate.city:
        target.city = duplicate.city
    if target.location is None and duplicate.location is not None:
        target.location = duplicate.location
    target.first_seen_at = min(target.first_seen_at, duplicate.first_seen_at)
    target.last_seen_at = max(target.last_seen_at, duplicate.last_seen_at)
    if duplicate.status == ListingStatus.ACTIVE:
        target.status = ListingStatus.ACTIVE
        target.inactive_at = None


def _merge_preferences(session, target: Property, duplicate: Property) -> int:
    moved = 0
    rows = list(
        session.scalars(
            select(CandidatePropertyPreference).where(
                CandidatePropertyPreference.property_id == duplicate.id
            )
        )
    )
    for row in rows:
        target_row = session.scalar(
            select(CandidatePropertyPreference).where(
                CandidatePropertyPreference.profile_id == row.profile_id,
                CandidatePropertyPreference.property_id == target.id,
            )
        )
        if target_row is None:
            row.property_id = target.id
            moved += 1
            continue
        target_row.favorite = bool(target_row.favorite or row.favorite)
        target_row.hidden = bool(target_row.hidden or row.hidden)
        viewed = [value for value in (target_row.viewed_at, row.viewed_at) if value is not None]
        target_row.viewed_at = min(viewed) if viewed else None
        target_row.created_at = min(target_row.created_at, row.created_at)
        target_row.updated_at = max(target_row.updated_at, row.updated_at)
        session.delete(row)
        moved += 1
    return moved


def _merge_image(session, target: Property, duplicate: Property) -> int:
    source_image = session.scalar(
        select(PropertyImage).where(PropertyImage.property_id == duplicate.id)
    )
    if source_image is None:
        return 0
    target_image = session.scalar(
        select(PropertyImage).where(PropertyImage.property_id == target.id)
    )
    if target_image is None:
        source_image.property_id = target.id
        return 1

    # Prefer an already cached image. If the direct target has no cached image but the
    # duplicate does, transfer the source-backed cache metadata before removing the extra row.
    if target_image.status != "cached" and source_image.status == "cached":
        target_image.property_listing_id = source_image.property_listing_id
        target_image.source_image_url = source_image.source_image_url
        target_image.local_filename = source_image.local_filename
        target_image.status = source_image.status
        target_image.attempts = max(target_image.attempts, source_image.attempts)
        target_image.last_attempt_at = source_image.last_attempt_at
        target_image.retry_after = source_image.retry_after
        target_image.fetched_at = source_image.fetched_at
        target_image.last_error = source_image.last_error
        target_image.updated_at = max(target_image.updated_at, source_image.updated_at)
    session.delete(source_image)
    return 1


def _fmt(row: Property) -> str:
    return (
        f"property={row.id} first_seen={row.first_seen_at.isoformat()} "
        f"price={row.price_eur} living={row.living_area_m2} plot={row.plot_area_m2} "
        f"title={row.title}"
    )


def main() -> None:
    args = parse_args()
    needle = (args.needle or "").strip().casefold()

    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(Property, PropertyListing, Source.name)
                .join(PropertyListing, PropertyListing.property_id == Property.id)
                .join(Source, Source.id == PropertyListing.source_id)
                .where(
                    Property.status == ListingStatus.ACTIVE,
                    PropertyListing.status == ListingStatus.ACTIVE,
                    Source.name.in_(_SOURCE_NAMES),
                )
                .order_by(Property.id, PropertyListing.id)
            )
        )

        properties: dict[int, Property] = {}
        sources_by_property: dict[int, set[str]] = defaultdict(set)
        urls_by_property: dict[int, list[str]] = defaultdict(list)
        groups: dict[PropertyDuplicateKey, set[int]] = defaultdict(set)

        for prop, listing, source_name in rows:
            if "/wohnwerk-fallback/" in listing.url:
                continue
            if needle and needle not in prop.title.casefold() and needle not in listing.url.casefold():
                continue
            key = property_duplicate_key(
                postal_code=prop.postal_code,
                price_eur=prop.price_eur,
                title=prop.title,
            )
            if key is None:
                continue
            properties[prop.id] = prop
            sources_by_property[prop.id].add(source_name)
            urls_by_property[prop.id].append(listing.url)
            groups[key].add(prop.id)

        merge_pairs: list[tuple[Property, Property]] = []
        skipped_conflicts = 0
        for property_ids in groups.values():
            if len(property_ids) != 2:
                continue
            left_id, right_id = sorted(property_ids)
            left = properties[left_id]
            right = properties[right_id]
            left_sources = sources_by_property[left_id]
            right_sources = sources_by_property[right_id]

            # Require one direct sREAL canonical and one IMMMO canonical. Already-merged
            # rows or ambiguous multi-source canonicals are deliberately left untouched.
            if left_sources == {"sreal.at"} and right_sources == {"immmo.at"}:
                target, duplicate = left, right
            elif right_sources == {"sreal.at"} and left_sources == {"immmo.at"}:
                target, duplicate = right, left
            else:
                continue

            if not properties_have_compatible_duplicate_facts(target, duplicate):
                skipped_conflicts += 1
                continue
            merge_pairs.append((target, duplicate))

        print(f"deterministic_duplicate_groups={len(merge_pairs)}")
        print(f"skipped_area_conflicts={skipped_conflicts}")
        for target, duplicate in merge_pairs:
            print("---")
            print(f"TARGET   {_fmt(target)}")
            for url in urls_by_property[target.id]:
                print(f"  sreal: {url}")
            print(f"DUPLICATE {_fmt(duplicate)}")
            for url in urls_by_property[duplicate.id]:
                print(f"  immmo: {url}")

        if not args.apply:
            print("dry_run=yes; re-run with --apply to merge exactly the groups above")
            return

        moved_listings = 0
        merged_preferences = 0
        merged_images = 0
        deleted_properties = 0
        for target, duplicate in merge_pairs:
            _merge_metadata(target, duplicate)
            merged_preferences += _merge_preferences(session, target, duplicate)
            merged_images += _merge_image(session, target, duplicate)

            listings = list(
                session.scalars(
                    select(PropertyListing).where(PropertyListing.property_id == duplicate.id)
                )
            )
            for listing in listings:
                listing.property = target
                moved_listings += 1

            session.flush()
            session.delete(duplicate)
            deleted_properties += 1

        session.commit()
        print(
            f"applied=yes groups={len(merge_pairs)} moved_listings={moved_listings} "
            f"merged_preferences={merged_preferences} merged_images={merged_images} "
            f"deleted_properties={deleted_properties} at={datetime.now(UTC).isoformat()}"
        )


if __name__ == "__main__":
    main()
