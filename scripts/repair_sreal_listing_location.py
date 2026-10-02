from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

import httpx
from sqlalchemy import or_, select

from app.database import SessionLocal
from app.models import ListingStatus, PostalCode, PropertyListing, Source
from app.sources.property.sreal_detail import parse_sreal_detail_page

HEADERS = {
    "User-Agent": "WohnWerk/0.4 (+private self-hosted Austrian property search; targeted repair)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Re-read one active s REAL detail page and repair only canonical "
            "postal/city/location metadata. Dry-run by default."
        )
    )
    parser.add_argument(
        "needle",
        help="s REAL source listing ID or URL fragment identifying exactly one active listing.",
    )
    parser.add_argument("--apply", action="store_true", help="Persist the location repair.")
    return parser.parse_args()


def _matching_listing(session, needle: str) -> PropertyListing:
    source = session.scalar(select(Source).where(Source.name == "sreal.at"))
    if source is None:
        raise SystemExit("sreal.at source not found")

    like = f"%{needle}%"
    rows = list(
        session.scalars(
            select(PropertyListing)
            .where(
                PropertyListing.source_id == source.id,
                PropertyListing.status == ListingStatus.ACTIVE,
                or_(
                    PropertyListing.source_listing_id.ilike(like),
                    PropertyListing.url.ilike(like),
                ),
            )
            .order_by(PropertyListing.id)
        )
    )
    if len(rows) != 1:
        raise SystemExit(f"expected exactly one active s REAL listing, found {len(rows)}")
    return rows[0]


async def _fetch(url: str) -> tuple[str, str]:
    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        if (response.url.host or "").casefold() not in {"sreal.at", "www.sreal.at"}:
            raise RuntimeError(f"s REAL redirected off-site: {response.url!s}")
        return response.text, str(response.url)


async def main() -> None:
    args = parse_args()
    needle = args.needle.strip()
    if not needle:
        raise SystemExit("needle is empty")

    with SessionLocal() as session:
        listing = _matching_listing(session, needle)
        property_row = listing.property
        html, final_url = await _fetch(listing.url)
        detail = parse_sreal_detail_page(html, page_url=final_url)

        if detail.listing_id != listing.source_listing_id:
            raise SystemExit(
                "detail listing ID mismatch: "
                f"{detail.listing_id!r} != {listing.source_listing_id!r}"
            )
        if not detail.postal_code or not detail.city:
            raise SystemExit("detail page did not expose an explicit postal code and city")

        postal = session.get(PostalCode, detail.postal_code)
        if postal is None:
            raise SystemExit(
                f"detail postal code {detail.postal_code!r} is not in the local reference table"
            )

        print(f"listing={listing.id} property={property_row.id}")
        print(f"old_location={property_row.postal_code!r} {property_row.city!r}")
        print(f"detail_location={detail.postal_code!r} {detail.city!r}")

        if not args.apply:
            print("mode=dry-run no database changes")
            return

        property_row.postal_code = postal.postal_code
        property_row.city = detail.city
        property_row.location = postal.location
        property_row.location_source = postal.location_source
        property_row.location_method = postal.location_method

        payload = dict(listing.raw_payload or {})
        payload["source_postal_code"] = detail.postal_code
        payload["detail_postal_code"] = detail.postal_code
        payload["detail_city"] = detail.city
        payload["targeted_location_repair_at"] = datetime.now(UTC).isoformat()
        payload["targeted_location_repair_policy"] = "sreal-detail-location-repair-v1"
        listing.raw_payload = payload

        session.commit()
        print("mode=applied")


if __name__ == "__main__":
    asyncio.run(main())
