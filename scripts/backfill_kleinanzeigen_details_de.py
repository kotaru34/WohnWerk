"""Operator-only bounded enrichment of existing Kleinanzeigen house listings.

Dry-run plan by default: no HTTP requests and no writes. Explicit --execute and
--confirm-provider-terms-reviewed required. Requires separately authorized
Sentinel permission for production. Never retains seller contact/description.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.database import SessionLocal
from app.models import PropertyListing, Source
from app.property_heating import heating_evidence_from_payload, merge_heating_into_payload
from app.sources.base import RawProperty
from app.sources.property.kleinanzeigen_de import KleinanzeigenGermanyPropertySource

MAX_BACKFILL = 8


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--listing-id", action="append", required=True, dest="listing_ids")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--confirm-provider-terms-reviewed", action="store_true")
    p.add_argument("--delay", type=float, default=3.0)
    return p


def validate_ids(ids: list[str]) -> list[str]:
    if not 1 <= len(ids) <= MAX_BACKFILL or len(set(ids)) != len(ids):
        raise ValueError("Require 1..8 distinct listing IDs")
    if any(re.fullmatch(r"\d{8,12}", item) is None for item in ids):
        raise ValueError("Listing IDs must be 8..12 digits")
    return ids


def find_listing(session, listing_id: str) -> PropertyListing | None:
    return session.scalar(
        select(PropertyListing).join(Source, Source.id == PropertyListing.source_id)
        .where(
            Source.name == "kleinanzeigen-de",
            Source.config["country_code"].astext == "DE",
            PropertyListing.source_listing_id == listing_id,
        )
    )


async def run_selected(
    ids: list[str], *, execute: bool, terms_reviewed: bool, delay: float,
) -> int:
    ids = validate_ids(ids)
    if delay < 2.0:
        raise ValueError("Delay below 2 seconds not allowed")
    if execute and not terms_reviewed:
        raise ValueError("--confirm-provider-terms-reviewed required for execution")

    with SessionLocal() as db:
        existing = [item for item in ids if find_listing(db, item) is not None]
    summary = {
        "requested": len(ids), "existing": len(existing),
        "detail_checked": 0, "enriched": 0,
        "plot_updates": 0, "plot_conflicts": 0,
        "mode": "execute" if execute else "plan",
    }
    if not execute:
        print(json.dumps(summary, sort_keys=True))
        return 0

    adapter = KleinanzeigenGermanyPropertySource(
        request_delay_seconds=delay, detail_checks_per_shard=1,
    )
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=False,
        headers={
            "User-Agent": "WohnWerk/0.4 (+private self-hosted German property search)",
            "Accept": "text/html",
        },
    ) as client:
        for listing_id in existing:
            with SessionLocal() as db:
                original = find_listing(db, listing_id)
                if original is None:
                    continue
                url = original.url
            item = RawProperty(
                source_listing_id=listing_id, url=url,
                title="public detail field enrichment only", raw_payload={},
            )
            verified = await adapter._enrich_public_detail(client, item)
            summary["detail_checked"] += 1
            if not verified:
                continue
            with SessionLocal() as db:
                listing = find_listing(db, listing_id)
                if listing is None or listing.url != url:
                    continue
                payload = merge_heating_into_payload(
                    listing.raw_payload,
                    heating_evidence_from_payload(item.raw_payload),
                )
                payload.update({
                    key: value for key, value in item.raw_payload.items()
                    if key not in {"heating_types", "heating_evidence"}
                })
                target = listing.property
                if item.plot_area_m2 is not None:
                    if target.plot_area_m2 is None:
                        target.plot_area_m2 = item.plot_area_m2
                        summary["plot_updates"] += 1
                    elif abs(Decimal(target.plot_area_m2) - item.plot_area_m2) > Decimal("0.01"):
                        payload["plot_area_source_conflict"] = True
                        summary["plot_conflicts"] += 1
                listing.raw_payload = payload
                db.commit()
                summary["enriched"] += 1
    print(json.dumps(summary, sort_keys=True))
    return 0


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(run_selected(
        args.listing_ids, execute=args.execute,
        terms_reviewed=args.confirm_provider_terms_reviewed, delay=args.delay,
    )))


if __name__ == "__main__":
    main()
