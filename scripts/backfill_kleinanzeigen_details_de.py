"""Backfill typed Kleinanzeigen detail facts for already persisted DE house listings.

Dry-run by default. --execute performs low-rate public detail GETs for every active
Kleinanzeigen listing still missing detail enrichment (or explicit --listing-id values).
Stops on source-wide access gates; never stores seller contacts or full descriptions.
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
from app.models import ListingStatus, PropertyListing, Source
from app.property_heating import heating_evidence_from_payload, merge_heating_into_payload
from app.sources.base import RawProperty, SourceFetchError
from app.sources.property.kleinanzeigen_de import KleinanzeigenGermanyPropertySource


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--listing-id", action="append", dest="listing_ids",
        help="Optional exact listing ID; repeatable. Omit to process all pending active rows.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Optional diagnostic/operational cap. Default: all pending rows.",
    )
    return parser


def _valid_ids(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    if not values or len(set(values)) != len(values):
        raise ValueError("listing IDs must be distinct")
    if any(re.fullmatch(r"\d{8,12}", item) is None for item in values):
        raise ValueError("listing IDs must be 8..12 digits")
    return values


def _source(session) -> Source:
    source = session.scalar(select(Source).where(Source.name == "kleinanzeigen-de"))
    if source is None:
        raise RuntimeError("Kleinanzeigen source is not configured")
    if str((source.config or {}).get("country_code") or "").upper() != "DE":
        raise RuntimeError("Kleinanzeigen source country is not DE")
    return source


def pending_listing_ids(
    *, listing_ids: list[str] | None = None, limit: int | None = None,
) -> list[str]:
    requested = _valid_ids(listing_ids)
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be positive")
    with SessionLocal() as session:
        source = _source(session)
        rows = list(session.scalars(
            select(PropertyListing)
            .where(
                PropertyListing.source_id == source.id,
                PropertyListing.status == ListingStatus.ACTIVE,
            )
            .order_by(PropertyListing.id)
        ))
    if requested is not None:
        by_id = {row.source_listing_id: row for row in rows}
        missing = [item for item in requested if item not in by_id]
        if missing:
            raise ValueError(f"unknown active Kleinanzeigen listing IDs: {', '.join(missing)}")
        selected = requested
    else:
        selected = [
            row.source_listing_id for row in rows
            if not isinstance(row.raw_payload, dict)
            or row.raw_payload.get("detail_enriched") is not True
        ]
    return selected[:limit] if limit is not None else selected


def _listing(session, source_id: int, listing_id: str) -> PropertyListing | None:
    return session.scalar(
        select(PropertyListing).where(
            PropertyListing.source_id == source_id,
            PropertyListing.source_listing_id == listing_id,
            PropertyListing.status == ListingStatus.ACTIVE,
        )
    )


async def run_backfill(
    ids: list[str], *, execute: bool, delay: float,
) -> int:
    if delay < 2.0:
        raise ValueError("Delay below 2 seconds is not allowed")
    summary = {
        "requested": len(ids), "detail_checked": 0, "enriched": 0,
        "plot_updates": 0, "plot_conflicts": 0, "unchanged": 0,
        "mode": "execute" if execute else "plan",
    }
    if not execute:
        print(json.dumps(summary, sort_keys=True))
        return 0

    adapter = KleinanzeigenGermanyPropertySource(
        request_delay_seconds=delay, detail_checks_per_shard=1,
    )
    headers = {
        "User-Agent": "WohnWerk/0.4 (+private self-hosted German property search)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
    }
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=False, headers=headers,
    ) as client:
        for listing_id in ids:
            with SessionLocal() as session:
                source = _source(session)
                listing = _listing(session, source.id, listing_id)
                if listing is None:
                    summary["unchanged"] += 1
                    continue
                url = listing.url
            item = RawProperty(
                source_listing_id=listing_id,
                url=url,
                title="typed detail enrichment",
                raw_payload={"country_code": "DE"},
            )
            try:
                verified = await adapter._enrich_public_detail(client, item)
            except SourceFetchError as exc:
                summary["halted"] = True
                summary["halt_reason"] = type(exc).__name__
                print(json.dumps(summary, sort_keys=True))
                return 1
            summary["detail_checked"] += 1
            if not verified:
                summary["unchanged"] += 1
                continue

            with SessionLocal() as session:
                source = _source(session)
                listing = _listing(session, source.id, listing_id)
                if listing is None or listing.url != url:
                    summary["unchanged"] += 1
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
                        payload["plot_area_conflicting_source_value_m2"] = str(item.plot_area_m2)
                        summary["plot_conflicts"] += 1
                listing.raw_payload = payload
                session.commit()
                summary["enriched"] += 1
    print(json.dumps(summary, sort_keys=True))
    return 0


async def async_main() -> int:
    args = build_parser().parse_args()
    ids = pending_listing_ids(listing_ids=args.listing_ids, limit=args.limit)
    return await run_backfill(ids, execute=args.execute, delay=args.delay)


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
