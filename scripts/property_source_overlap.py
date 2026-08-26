from __future__ import annotations

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Property, PropertyListing, Source


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
        overlap_count = session.scalar(select(func.count()).select_from(overlap_ids)) or 0

        print(f"sreal_listings={sreal_total} detail_enriched={sreal_enriched}")
        print(f"immmo_sreal_exact_url_overlap={overlap_count}")

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
