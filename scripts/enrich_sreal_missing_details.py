from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ListingStatus, PostalCode, PropertyListing, Source
from app.sources.base import RawProperty
from app.sources.property.sreal_detail import enrich_sreal_property, parse_sreal_detail_page


HEADERS = {
    "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian property search)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich only active s REAL listings that still lack successful detail metadata."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.6,
        help="Delay between detail requests (default: 0.6 seconds).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of missing detail pages to process.",
    )
    return parser.parse_args()


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    last_error: httpx.HTTPError | RuntimeError | None = None
    for attempt in range(3):
        try:
            response = await client.get(url)
            if response.status_code in {429, 500, 502, 503, 504}:
                response.raise_for_status()
            response.raise_for_status()
            if (response.url.host or "").casefold() not in {"sreal.at", "www.sreal.at"}:
                raise RuntimeError(
                    f"s REAL redirected off-site: requested={url!r} final={str(response.url)!r}"
                )
            return response
        except (httpx.HTTPError, RuntimeError) as exc:
            last_error = exc
            if attempt == 2:
                raise
            await asyncio.sleep(2**attempt)
    raise RuntimeError("unreachable") from last_error


def _as_raw(listing: PropertyListing) -> RawProperty:
    property_row = listing.property
    return RawProperty(
        source_listing_id=listing.source_listing_id,
        url=listing.url,
        title=property_row.title,
        description=property_row.description,
        price_eur=property_row.price_eur,
        living_area_m2=property_row.living_area_m2,
        plot_area_m2=property_row.plot_area_m2,
        postal_code=property_row.postal_code,
        city=property_row.city,
        raw_payload=dict(listing.raw_payload or {}),
    )


def _apply_enrichment(session: Session, listing: PropertyListing, enriched: RawProperty) -> None:
    property_row = listing.property
    if enriched.title:
        property_row.title = enriched.title
    if enriched.description is not None:
        property_row.description = enriched.description
    if enriched.price_eur is not None:
        property_row.price_eur = enriched.price_eur
    if enriched.living_area_m2 is not None:
        property_row.living_area_m2 = enriched.living_area_m2
    if enriched.plot_area_m2 is not None:
        property_row.plot_area_m2 = enriched.plot_area_m2
    if enriched.city:
        property_row.city = enriched.city

    if enriched.postal_code:
        postal = session.get(PostalCode, enriched.postal_code)
        if postal is not None:
            property_row.postal_code = postal.postal_code
            property_row.location = postal.location

    listing.raw_payload = dict(enriched.raw_payload)


async def async_main() -> int:
    args = parse_args()
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == "sreal.at"))
        if source is None:
            raise SystemExit("sreal.at source not configured")

        query = (
            select(PropertyListing)
            .where(
                PropertyListing.source_id == source.id,
                PropertyListing.status == ListingStatus.ACTIVE,
                PropertyListing.raw_payload.op("->>")("detail_enriched").is_distinct_from("true"),
            )
            .order_by(PropertyListing.id)
        )
        if args.limit is not None:
            query = query.limit(max(0, args.limit))
        listings = list(session.scalars(query))

        print(f"missing_detail_enrichment={len(listings)}")
        if not listings:
            return 0

        succeeded = 0
        failed = 0
        async with httpx.AsyncClient(
            headers=HEADERS,
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            for index, listing in enumerate(listings):
                if index and args.delay > 0:
                    await asyncio.sleep(args.delay)
                try:
                    response = await _get(client, listing.url)
                    detail = parse_sreal_detail_page(response.text, page_url=str(response.url))
                    enriched = enrich_sreal_property(_as_raw(listing), detail)
                    _apply_enrichment(session, listing, enriched)
                    succeeded += 1
                except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                    payload = dict(listing.raw_payload or {})
                    payload["detail_enriched"] = False
                    payload["detail_enrichment_error"] = f"{type(exc).__name__}: {exc}"[:500]
                    payload["detail_enrichment_attempted_at"] = datetime.now(UTC).isoformat()
                    listing.raw_payload = payload
                    failed += 1

        session.commit()
        print(f"detail_enrichment_succeeded={succeeded} failed={failed}")
        return 0 if failed == 0 else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
