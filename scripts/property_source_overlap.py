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

        rows = list(
            session.execute(
                select(
                    Property.id,
                    Property.title,
                    Property.postal_code,
                    Property.city,
                    func.array_agg(Source.name.order_by(Source.name)),
                    func.array_agg(PropertyListing.url.order_by(Source.name)),
                )
                .join(PropertyListing, PropertyListing.property_id == Property.id)
                .join(Source, Source.id == PropertyListing.source_id)
                .where(Property.id.in_(select(overlap_ids.c.property_id)))
                .group_by(Property.id)
                .order_by(Property.id)
                .limit(20)
            )
        )
        for property_id, title, postal_code, city, source_names, urls in rows:
            location = " ".join(part for part in (postal_code, city) if part) or "unknown"
            print(f"  property[{property_id}] {location} | {title}")
            for source_name, url in zip(source_names, urls, strict=True):
                print(f"    {source_name}: {url}")


if __name__ == "__main__":
    main()
