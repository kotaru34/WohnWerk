from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import exists, select

from app.database import SessionLocal
from app.ingestion.listing_identity import stable_external_identity
from app.models import ListingStatus, Property, PropertyListing, Source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge historical IMMMO/s REAL canonical duplicates only when both URLs "
            "contain the same provider-issued s REAL object ID."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deterministic merges. Without this flag the command is read-only.",
    )
    return parser.parse_args()


def _merge_direct_metadata(target: Property, direct: Property) -> None:
    """Prefer non-null metadata from the direct s REAL canonical row."""
    if direct.title:
        target.title = direct.title
    if direct.description is not None:
        target.description = direct.description
    if direct.price_eur is not None:
        target.price_eur = direct.price_eur
    if direct.living_area_m2 is not None:
        target.living_area_m2 = direct.living_area_m2
    if direct.plot_area_m2 is not None:
        target.plot_area_m2 = direct.plot_area_m2
    if direct.postal_code is not None:
        target.postal_code = direct.postal_code
        target.location = direct.location
    if direct.city:
        target.city = direct.city
    target.first_seen_at = min(target.first_seen_at, direct.first_seen_at)
    target.last_seen_at = max(target.last_seen_at, direct.last_seen_at)
    if direct.status == ListingStatus.ACTIVE:
        target.status = ListingStatus.ACTIVE
        target.inactive_at = None


def _fmt_location(row: Property) -> str:
    return " ".join(part for part in (row.postal_code, row.city) if part) or "unknown"


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        sources = {
            source.name: source
            for source in session.scalars(
                select(Source).where(Source.name.in_(["immmo.at", "sreal.at"]))
            )
        }
        immmo = sources.get("immmo.at")
        sreal = sources.get("sreal.at")
        if immmo is None or sreal is None:
            raise SystemExit("Need both immmo.at and sreal.at source rows.")

        rows = list(
            session.scalars(
                select(PropertyListing)
                .where(PropertyListing.source_id.in_([immmo.id, sreal.id]))
                .order_by(PropertyListing.id)
            )
        )
        groups: dict[str, list[PropertyListing]] = {}
        for listing in rows:
            identity = stable_external_identity(listing.url)
            if identity is not None:
                groups.setdefault(identity, []).append(listing)

        merge_groups: list[tuple[str, list[PropertyListing]]] = []
        for identity, listings in groups.items():
            source_ids = {listing.source_id for listing in listings}
            property_ids = {listing.property_id for listing in listings}
            if {immmo.id, sreal.id}.issubset(source_ids) and len(property_ids) > 1:
                merge_groups.append((identity, listings))

        print(f"deterministic_duplicate_groups={len(merge_groups)}")
        for identity, listings in merge_groups[:30]:
            immmo_listing = next(item for item in listings if item.source_id == immmo.id)
            sreal_listing = next(item for item in listings if item.source_id == sreal.id)
            print(
                f"  {identity}: immmo_property={immmo_listing.property_id} "
                f"sreal_property={sreal_listing.property_id} "
                f"location={_fmt_location(sreal_listing.property)}"
            )
        if len(merge_groups) > 30:
            print(f"  ... {len(merge_groups) - 30} more")

        if not args.apply:
            print("dry_run=yes; re-run with --apply to merge these deterministic duplicates")
            return

        orphan_candidates: set[int] = set()
        moved_listings = 0
        for _identity, listings in merge_groups:
            immmo_listing = next(item for item in listings if item.source_id == immmo.id)
            target = immmo_listing.property

            direct_rows = [item.property for item in listings if item.source_id == sreal.id]
            for direct in direct_rows:
                if direct.id != target.id:
                    _merge_direct_metadata(target, direct)

            for listing in listings:
                if listing.property_id == target.id:
                    continue
                orphan_candidates.add(listing.property_id)
                listing.property = target
                moved_listings += 1

        session.flush()
        deleted_properties = 0
        for property_id in orphan_candidates:
            has_listing = session.scalar(
                select(exists().where(PropertyListing.property_id == property_id))
            )
            if has_listing:
                continue
            property_row = session.get(Property, property_id)
            if property_row is not None:
                session.delete(property_row)
                deleted_properties += 1

        session.commit()
        print(
            f"applied=yes groups={len(merge_groups)} moved_listings={moved_listings} "
            f"deleted_orphan_properties={deleted_properties} "
            f"at={datetime.now(UTC).isoformat()}"
        )


if __name__ == "__main__":
    main()
