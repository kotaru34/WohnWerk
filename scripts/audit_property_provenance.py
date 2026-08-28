from __future__ import annotations

import argparse

from sqlalchemy import or_, select

from app.database import SessionLocal
from app.models import Property, PropertyListing, Source
from app.property_visibility import product_visible_property_condition


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect canonical/source provenance for a property URL or identifier."
    )
    parser.add_argument(
        "needle",
        help="URL fragment, source listing ID, or distinctive title fragment.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    like = f"%{args.needle}%"

    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(PropertyListing, Property, Source)
                .join(Property, Property.id == PropertyListing.property_id)
                .join(Source, Source.id == PropertyListing.source_id)
                .where(
                    or_(
                        PropertyListing.url.ilike(like),
                        PropertyListing.source_listing_id.ilike(like),
                        Property.title.ilike(like),
                    )
                )
                .order_by(Property.id, PropertyListing.id)
            )
        )

        if not rows:
            print("matches=0")
            return

        print(f"matches={len(rows)}")
        visible_cache: dict[int, bool] = {}
        for listing, property_row, source in rows:
            if property_row.id not in visible_cache:
                visible_cache[property_row.id] = (
                    session.scalar(
                        select(Property.id).where(
                            Property.id == property_row.id,
                            product_visible_property_condition(),
                        )
                    )
                    is not None
                )

            payload = listing.raw_payload or {}
            print()
            print(f"property_id={property_row.id}")
            print(f"title={property_row.title}")
            print(f"canonical_price_eur={property_row.price_eur}")
            print(f"father_visible={str(visible_cache[property_row.id]).lower()}")
            print(f"source={source.name}")
            print(f"source_listing_id={listing.source_listing_id}")
            print(f"listing_status={listing.status}")
            print(f"listing_url={listing.url}")
            print(f"last_seen_crawl_run_id={listing.last_seen_crawl_run_id}")
            print(f"format={payload.get('format')}")
            print(f"price_semantics={payload.get('price_semantics')}")
            print(f"source_price_eur={payload.get('source_price_eur')}")
            print(f"product_visible={payload.get('product_visible')}")
            print(f"product_visibility_reason={payload.get('product_visibility_reason')}")
            print(f"discovery_url={payload.get('discovery_url')}")


if __name__ == "__main__":
    main()
