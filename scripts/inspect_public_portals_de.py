"""Read-only, account-free HTML-source diagnostic; never touches the WohnWerk DB.

Runs only bounded public search pages with explicit source IDs. Use manually
before opting any new German provider into a recurring refresh schedule.
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


def selected_shards(adapter: PublicGermanHouseSource, *, regional: bool):
    shards = adapter.default_shards()
    return shards if regional else shards[:1]


async def inspect_provider(name: str, *, regional: bool) -> bool:
    adapter = PROVIDERS[name]()
    healthy = True
    for shard in selected_shards(adapter, regional=regional):
        try:
            batch = await adapter.fetch_shard(shard)
        except SourceFetchError as exc:
            print(f"FAIL {name}/{shard.key}: {exc}")
            healthy = False
            continue
        eligible = list(batch.items)
        seen = batch.next_cursor.get("frontier_cards_seen", 0)
        print(
            f"OK {name}/{shard.key}: public cards={seen}, "
            f"€30–200k candidates={len(eligible)}, pages={batch.pages_fetched}"
        )
        for item in eligible[:3]:
            print(f"  {item.source_listing_id} | {item.price_eur} € | {item.url}")
        if batch.coverage_complete:
            print("FAIL: bounded discovery must not claim full source coverage")
            healthy = False
    return healthy


async def run(*, provider: str, regional: bool) -> int:
    names = list(PROVIDERS) if provider == "all" else [provider]
    results = [await inspect_provider(name, regional=regional) for name in names]
    if not all(results):
        print("Live diagnostic failed; provider must remain manual-only.")
        return 1
    print("Diagnostic passed. Review terms, sample quality and yield before activation.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["all", *PROVIDERS], default="all")
    parser.add_argument(
        "--regional", action="store_true",
        help="Include four additional immobilien.de public city first-page shards",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(provider=args.provider, regional=args.regional)))
