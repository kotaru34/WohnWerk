from __future__ import annotations

import argparse
import asyncio

import httpx
from geoalchemy2.shape import to_shape
from sqlalchemy import select

from app.database import SessionLocal
from app.internet_access import (
    BBA_SOURCE_NAME,
    INTERNET_GRID_ELIGIBLE_LOCATION_PRECISIONS,
    active_immoscout_listings_for_internet,
    broadband_dataset_path,
    fetch_immoscout_telekom_evidence,
    lookup_breitbandatlas_grid,
    store_breitbandatlas_evidence,
    store_immoscout_telekom_evidence,
)
from app.models import ListingStatus, Property


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich German properties with source-backed fixed Internet evidence."
    )
    parser.add_argument("--listing-limit", type=int, default=30)
    parser.add_argument("--grid-limit", type=int, default=200)
    return parser.parse_args()


async def enrich_listing_evidence(limit: int) -> tuple[int, int, int]:
    considered = 0
    matched = 0
    failed = 0
    with SessionLocal() as session:
        listings = active_immoscout_listings_for_internet(session, limit=max(1, limit))
        for listing in listings:
            considered += 1
            try:
                evidence = await fetch_immoscout_telekom_evidence(
                    listing.url,
                    expected_scout_id=listing.source_listing_id,
                )
            except httpx.HTTPError as exc:
                failed += 1
                print(
                    f"listing={listing.id} state=failed "
                    f"error={type(exc).__name__}:{str(exc)[:180]}"
                )
                continue

            if evidence is None:
                print(f"listing={listing.id} state=missing")
                continue

            store_immoscout_telekom_evidence(session, listing, evidence)
            matched += 1
            print(
                f"listing={listing.id} state=matched "
                f"availability={evidence.availability_state} "
                f"speed={evidence.max_download_mbps}"
            )
        session.commit()
    return considered, matched, failed


def enrich_grid_evidence(limit: int) -> tuple[int, int, int]:
    considered = 0
    matched = 0
    skipped = 0
    with SessionLocal() as session:
        dataset_path = broadband_dataset_path(session)
        if dataset_path is None:
            print(f"grid_source={BBA_SOURCE_NAME} state=unavailable")
            return 0, 0, 0

        properties = list(
            session.scalars(
                select(Property)
                .where(
                    Property.status == ListingStatus.ACTIVE,
                    Property.location.is_not(None),
                    Property.location_precision.in_(
                        tuple(sorted(INTERNET_GRID_ELIGIBLE_LOCATION_PRECISIONS))
                    ),
                )
                .order_by(Property.id)
                .limit(max(1, limit))
            )
        )
        for property_row in properties:
            considered += 1
            try:
                point = to_shape(property_row.location)
            except Exception as exc:
                skipped += 1
                print(
                    f"property={property_row.id} grid=skipped "
                    f"error={type(exc).__name__}:{str(exc)[:160]}"
                )
                continue

            cell = lookup_breitbandatlas_grid(
                dataset_path,
                longitude=float(point.x),
                latitude=float(point.y),
            )
            if cell is None:
                skipped += 1
                print(f"property={property_row.id} grid=outside_dataset")
                continue

            store_breitbandatlas_evidence(session, property_row, cell)
            matched += 1
            print(
                f"property={property_row.id} grid={cell.raster_id} "
                f"max_defensible={cell.max_defensible_download_mbps}"
            )
        session.commit()
    return considered, matched, skipped


async def async_main() -> int:
    args = parse_args()
    listing_considered, listing_matched, listing_failed = await enrich_listing_evidence(
        args.listing_limit
    )
    grid_considered, grid_matched, grid_skipped = enrich_grid_evidence(args.grid_limit)
    print(
        "internet_enrichment "
        f"listing_considered={listing_considered} "
        f"listing_matched={listing_matched} "
        f"listing_failed={listing_failed} "
        f"grid_considered={grid_considered} "
        f"grid_matched={grid_matched} "
        f"grid_skipped={grid_skipped}"
    )
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
