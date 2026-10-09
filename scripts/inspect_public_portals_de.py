"""Read-only, no-DB German source diagnostic with optional house-detail checks.

Raw listing cards are *not* evidence that a purchasable, built house exists;
a seller may advertise house-building services excluding the land in the price.
No login, contact extraction, database writes or CAPTCHA bypass.
"""

from __future__ import annotations

import argparse
import asyncio

from app.sources.base import SourceFetchError
from app.sources.property.public_portals_de import (
    ImmobilienDeGermanyPropertySource,
    OhneMaklerGermanyPropertySource,
    PublicGermanHouseSource,
)

PROVIDERS = {
    "ohne-makler-de": OhneMaklerGermanyPropertySource,
    "immobilien-de": ImmobilienDeGermanyPropertySource,
}


def selected_shards(
    adapter: PublicGermanHouseSource,
    *,
    regional: bool,
    frontier_key: str | None = None,
):
    shards = adapter.default_shards()
    if frontier_key is not None:
        matched = [shard for shard in shards if shard.key == frontier_key]
        if not matched:
            raise ValueError(f"Unknown whitelisted frontier: {frontier_key}")
        return matched
    return shards if regional else shards[:1]


async def inspect_provider(
    name: str,
    *,
    regional: bool,
    verify_details: bool = False,
    max_detail_checks: int = 8,
    frontier_key: str | None = None,
) -> bool:
    adapter = PROVIDERS[name](
        verify_details=verify_details,
        max_detail_checks_per_shard=max_detail_checks,
    )
    healthy = True
    all_candidate_ids: set[str] = set()
    all_verified_ids: set[str] = set()
    for shard in selected_shards(adapter, regional=regional, frontier_key=frontier_key):
        try:
            batch = await adapter.fetch_shard(shard)
        except SourceFetchError as exc:
            print(f"FAIL {name}/{shard.key}: {exc}")
            healthy = False
            if exc.halt_source:
                print("Source-wide access boundary reached; stopping further requests.")
                break
            continue

        cards = int(batch.next_cursor.get("frontier_cards_seen", 0))
        eligible = list(batch.items)
        verified = [
            item for item in eligible
            if item.raw_payload.get("public_house_detail_verified") is True
        ]
        all_candidate_ids.update(item.source_listing_id for item in eligible)
        all_verified_ids.update(item.source_listing_id for item in verified)
        print(
            f"OK {name}/{shard.key}: public cards={cards}, "
            f"€30–200k *unverified* leads={len(eligible)}, "
            f"public details checked={batch.next_cursor.get('detail_checked', 0)}, "
            f"verified existing houses={len(verified)}"
        )
        for item in eligible[:3]:
            evidence = item.raw_payload.get("public_house_detail_reason", "not_checked")
            print(
                f"  {item.source_listing_id} | {item.price_eur} € "
                f"| evidence={evidence} | {item.url}"
            )
        if batch.coverage_complete:
            print("FAIL: frontier discovery cannot claim full source coverage.")
            healthy = False

    print(
        f"{name}: unique budget-card IDs={len(all_candidate_ids)}, "
        f"verified-house IDs={len(all_verified_ids)}"
    )
    if verify_details and not all_verified_ids:
        print(f"FAIL {name}: zero verified purchasable houses; do not activate.")
        healthy = False
    elif not verify_details:
        print(f"{name}: raw cards only; NEVER activate from this result alone.")
    return healthy


async def run(
    *,
    provider: str,
    regional: bool,
    verify_details: bool = False,
    max_detail_checks: int = 8,
    frontier_key: str | None = None,
) -> int:
    names = list(PROVIDERS) if provider == "all" else [provider]
    results = [
        await inspect_provider(
            name,
            regional=regional,
            verify_details=verify_details,
            max_detail_checks=max_detail_checks,
            frontier_key=frontier_key,
        )
        for name in names
    ]
    if not all(results):
        print("Source not accepted; provider must remain manual-only.")
        return 1
    if verify_details:
        print("Detail evidence passed. Review provider terms, yields and quality before activation.")
    else:
        print("Only source connectivity/card parsing passed; detail verification NOT performed.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["all", *PROVIDERS], default="all")
    parser.add_argument(
        "--frontier",
        help="Restrict diagnostic to one exact, whitelisted public regional frontier",
    )
    parser.add_argument(
        "--regional", action="store_true",
        help="Inspect all whitelisted regional plus national first-page frontiers",
    )
    parser.add_argument(
        "--verify-details", action="store_true",
        help="Check a bounded number of public detail pages for built houses with land",
    )
    parser.add_argument(
        "--max-detail-checks", type=int, default=8,
        help="Number of price-eligible public detail pages per shard (0–10)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(
        provider=args.provider,
        regional=args.regional,
        verify_details=args.verify_details,
        max_detail_checks=args.max_detail_checks,
        frontier_key=args.frontier,
    )))
