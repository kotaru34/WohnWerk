from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Property, PropertyListing, Source

SREAL_ID_RE = re.compile(r"^/de/immobilie/(?P<listing_id>[^/]+)/", re.IGNORECASE)


def _sreal_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if host not in {"sreal.at", "www.sreal.at"}:
        return None
    match = SREAL_ID_RE.match(parsed.path)
    return match.group("listing_id") if match else None


def main() -> None:
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
            print("Need both immmo.at and sreal.at source rows before overlap analysis.")
            return

        sreal_total = session.scalar(
            select(func.count()).select_from(PropertyListing).where(
                PropertyListing.source_id == sreal.id
            )
        ) or 0
        sreal_enriched = session.scalar(
            select(func.count()).select_from(PropertyListing).where(
                PropertyListing.source_id == sreal.id,
                PropertyListing.raw_payload.op("->>")("detail_enriched") == "true",
            )
        ) or 0

        overlap_ids = (
            select(PropertyListing.property_id)
            .where(PropertyListing.source_id.in_([immmo.id, sreal.id]))
            .group_by(PropertyListing.property_id)
            .having(func.count(func.distinct(PropertyListing.source_id)) == 2)
            .subquery()
        )
        exact_property_overlap = session.scalar(
            select(func.count()).select_from(overlap_ids)
        ) or 0

        sreal_rows = list(
            session.execute(
                select(
                    PropertyListing.source_listing_id,
                    PropertyListing.property_id,
                    PropertyListing.url,
                ).where(PropertyListing.source_id == sreal.id)
            )
        )
        sreal_by_id = {
            listing_id: (property_id, url)
            for listing_id, property_id, url in sreal_rows
        }

        immmo_sreal_rows = list(
            session.execute(
                select(PropertyListing.property_id, PropertyListing.url).where(
                    PropertyListing.source_id == immmo.id,
                    PropertyListing.url.ilike("%sreal.at/%"),
                )
            )
        )
        immmo_by_sreal_id: dict[str, tuple[int, str]] = {}
        for property_id, url in immmo_sreal_rows:
            listing_id = _sreal_id(url)
            if listing_id is not None:
                immmo_by_sreal_id.setdefault(listing_id, (property_id, url))

        stable_ids = sorted(set(sreal_by_id) & set(immmo_by_sreal_id))
        already_merged = sum(
            sreal_by_id[listing_id][0] == immmo_by_sreal_id[listing_id][0]
            for listing_id in stable_ids
        )
        historical_duplicates = len(stable_ids) - already_merged

        print(f"sreal_listings={sreal_total} detail_enriched={sreal_enriched}")
        print(f"immmo_sreal_exact_url_overlap={exact_property_overlap}")
        print(
            "immmo_sreal_stable_id_overlap="
            f"{len(stable_ids)} already_merged={already_merged} "
            f"historical_duplicates={historical_duplicates}"
        )
        print(f"immmo_urls_pointing_to_sreal={len(immmo_by_sreal_id)}")

        for listing_id in stable_ids[:20]:
            sreal_property_id, sreal_url = sreal_by_id[listing_id]
            immmo_property_id, immmo_url = immmo_by_sreal_id[listing_id]
            state = "merged" if sreal_property_id == immmo_property_id else "duplicate"
            print(
                f"  sreal[{listing_id}] {state} "
                f"immmo_property={immmo_property_id} sreal_property={sreal_property_id}"
            )
            if immmo_url != sreal_url:
                print(f"    immmo: {immmo_url}")
                print(f"    sreal: {sreal_url}")

        properties = list(
            session.scalars(
                select(Property)
                .where(Property.id.in_(select(overlap_ids.c.property_id)))
                .order_by(Property.id)
                .limit(20)
            )
        )
        for property_row in properties:
            location = (
                " ".join(
                    part
                    for part in (property_row.postal_code, property_row.city)
                    if part
                )
                or "unknown"
            )
            print(f"  property[{property_row.id}] {location} | {property_row.title}")
            listings = session.execute(
                select(Source.name, PropertyListing.url)
                .join(Source, Source.id == PropertyListing.source_id)
                .where(
                    PropertyListing.property_id == property_row.id,
                    PropertyListing.source_id.in_([immmo.id, sreal.id]),
                )
                .order_by(Source.name)
            )
            for source_name, url in listings:
                print(f"    {source_name}: {url}")


if __name__ == "__main__":
    main()
