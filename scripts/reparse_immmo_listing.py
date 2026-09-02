from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

import httpx
from sqlalchemy import or_, select

from app.database import SessionLocal
from app.ingestion.properties import _merge_listing_payload
from app.models import ListingStatus, PostalCode, PropertyListing, Source
from app.property_acquisition import annotate_property_items_by_budget
from app.property_thumbnail_cache import _comparison_url
from app.sources.property.immmo_v3 import parse_immmo_search_page

_LIVENESS_KEYS = (
    "source_liveness_policy",
    "source_liveness_required",
    "source_liveness_state",
    "source_liveness_checked_at",
    "source_liveness_status_code",
    "source_liveness_reason",
    "source_liveness_final_url",
    "source_liveness_last_live_at",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reparse one current IMMMO search card from its recorded discovery page. "
            "Dry-run by default; does not alter crawl lifecycle timestamps."
        )
    )
    parser.add_argument("needle", help="External URL/id fragment identifying one active listing.")
    parser.add_argument("--apply", action="store_true", help="Persist corrected parser fields.")
    return parser.parse_args()


def _matching_listing(session, needle: str) -> PropertyListing:
    source = session.scalar(select(Source).where(Source.name == "immmo.at"))
    if source is None:
        raise SystemExit("IMMMO source not found")

    like = f"%{needle}%"
    rows = list(
        session.scalars(
            select(PropertyListing)
            .where(
                PropertyListing.source_id == source.id,
                PropertyListing.status == ListingStatus.ACTIVE,
                or_(
                    PropertyListing.url.ilike(like),
                    PropertyListing.source_listing_id.ilike(like),
                ),
            )
            .order_by(PropertyListing.id)
        )
    )
    if len(rows) != 1:
        raise SystemExit(f"expected exactly one active IMMMO listing, found {len(rows)}")
    return rows[0]


async def _fetch(url: str) -> tuple[str, str]:
    headers = {
        "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian property search; targeted repair)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
    }
    async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text, str(response.url)


def _same_external_listing(left: str, right: str, needle: str) -> bool:
    left_key = _comparison_url(left)
    right_key = _comparison_url(right)
    if left_key and right_key and left_key == right_key:
        return True
    return needle in left and needle in right


async def main() -> None:
    args = parse_args()
    needle = args.needle.strip()
    if not needle:
        raise SystemExit("needle is empty")

    with SessionLocal() as session:
        listing = _matching_listing(session, needle)
        property_row = listing.property
        old_payload = dict(listing.raw_payload or {})
        discovery_url = old_payload.get("discovery_url")
        if not isinstance(discovery_url, str) or not discovery_url.startswith("https://"):
            raise SystemExit("listing has no usable discovery_url")

        html, final_url = await _fetch(discovery_url)
        page = parse_immmo_search_page(html, page_url=final_url)
        candidates = [
            item
            for item in page.items
            if _same_external_listing(listing.url, item.url, needle)
        ]
        if len(candidates) != 1:
            raise SystemExit(
                f"expected one matching card on discovery page, found {len(candidates)}"
            )
        item = candidates[0]
        if item.raw_payload.get("original_url_missing") is True:
            raise SystemExit("target reparsed as synthetic fallback; refusing update")

        incoming = dict(item.raw_payload)
        for key in _LIVENESS_KEYS:
            if key in old_payload:
                incoming[key] = old_payload[key]
        item.raw_payload = incoming
        annotate_property_items_by_budget([item])

        old_visible = old_payload.get("product_visible")
        old_reason = old_payload.get("product_visibility_reason")
        new_visible = item.raw_payload.get("product_visible")
        new_reason = item.raw_payload.get("product_visibility_reason")

        print(f"listing={listing.id} property={property_row.id}")
        print(f"discovery_url={discovery_url}")
        print(f"external_url={listing.url}")
        print(f"old_title={property_row.title!r}")
        print(f"new_title={item.title!r}")
        print(f"old_price_eur={property_row.price_eur}")
        print(f"new_price_eur={item.price_eur}")
        print(f"old_living_area_m2={property_row.living_area_m2}")
        print(f"new_living_area_m2={item.living_area_m2}")
        print(f"old_plot_area_m2={property_row.plot_area_m2}")
        print(f"new_plot_area_m2={item.plot_area_m2}")
        print(f"old_product_visible={old_visible}")
        print(f"new_product_visible={new_visible}")
        print(f"old_visibility_reason={old_reason}")
        print(f"new_visibility_reason={new_reason}")

        if not args.apply:
            print("mode=dry-run no database changes")
            return

        postal = (
            session.get(PostalCode, item.postal_code)
            if item.postal_code is not None
            else None
        )
        property_row.title = item.title
        if item.price_eur is not None:
            property_row.price_eur = item.price_eur
        if item.living_area_m2 is not None:
            property_row.living_area_m2 = item.living_area_m2
        if item.plot_area_m2 is not None:
            property_row.plot_area_m2 = item.plot_area_m2
        if postal is not None:
            property_row.postal_code = postal.postal_code
            property_row.location = postal.location
        if item.city:
            property_row.city = item.city

        merged = _merge_listing_payload(old_payload, dict(item.raw_payload))
        merged["targeted_reparse_at"] = datetime.now(UTC).isoformat()
        merged["targeted_reparse_policy"] = "immmo-targeted-reparse-2026-08-29-v1"
        listing.raw_payload = merged
        session.commit()
        print("mode=applied")


if __name__ == "__main__":
    asyncio.run(main())
