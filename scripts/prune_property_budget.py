from __future__ import annotations

import argparse

from sqlalchemy import delete, func, or_, select

from app.database import SessionLocal
from app.models import Property, PropertyListing
from app.property_acquisition import PROPERTY_MAX_PRICE_EUR, PROPERTY_MIN_PRICE_EUR


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove canonical properties that cannot satisfy the acquisition price budget."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete candidates. Default mode is read-only dry-run.",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=30,
        help="Number of candidate properties to print (default: 30).",
    )
    return parser.parse_args()


def _candidate_condition():
    return or_(
        Property.price_eur.is_(None),
        Property.price_eur < PROPERTY_MIN_PRICE_EUR,
        Property.price_eur > PROPERTY_MAX_PRICE_EUR,
    )


def main() -> None:
    args = parse_args()
    condition = _candidate_condition()

    with SessionLocal() as session:
        total = int(session.scalar(select(func.count()).select_from(Property)) or 0)
        unknown = int(
            session.scalar(
                select(func.count()).select_from(Property).where(Property.price_eur.is_(None))
            )
            or 0
        )
        below = int(
            session.scalar(
                select(func.count())
                .select_from(Property)
                .where(Property.price_eur < PROPERTY_MIN_PRICE_EUR)
            )
            or 0
        )
        above = int(
            session.scalar(
                select(func.count())
                .select_from(Property)
                .where(Property.price_eur > PROPERTY_MAX_PRICE_EUR)
            )
            or 0
        )
        candidates = unknown + below + above
        listing_count = int(
            session.scalar(
                select(func.count())
                .select_from(PropertyListing)
                .join(Property, Property.id == PropertyListing.property_id)
                .where(condition)
            )
            or 0
        )

        print(f"budget_eur={PROPERTY_MIN_PRICE_EUR}-{PROPERTY_MAX_PRICE_EUR}")
        print(f"properties_total={total}")
        print(f"candidates={candidates}")
        print(f"price_unknown={unknown}")
        print(f"price_below_min={below}")
        print(f"price_above_max={above}")
        print(f"source_listings_cascade={listing_count}")
        print("sample_candidates:")
        rows = list(
            session.execute(
                select(
                    Property.id,
                    Property.price_eur,
                    Property.postal_code,
                    Property.city,
                    Property.title,
                )
                .where(condition)
                .order_by(Property.id)
                .limit(max(0, args.sample))
            )
        )
        for row in rows:
            if row.price_eur is None:
                reason = "price_unknown"
            elif row.price_eur < PROPERTY_MIN_PRICE_EUR:
                reason = "price_below_min"
            else:
                reason = "price_above_max"
            print(
                f"  property={row.id} reason={reason} price={row.price_eur} "
                f"plz={row.postal_code or '-'} city={row.city or '-'}"
            )
            print(f"    title={row.title}")

        if not args.apply:
            print("mode=dry-run no database changes")
            return

        result = session.execute(delete(Property).where(condition))
        deleted = result.rowcount or 0
        session.commit()
        print("mode=apply")
        print(f"properties_deleted={deleted}")


if __name__ == "__main__":
    main()
