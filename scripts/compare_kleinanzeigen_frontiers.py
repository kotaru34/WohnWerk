"""Read-only, rate-limited account-free Kleinanzeigen frontier comparison.

No database access, credentials, seller messaging or detail-page requests. Both
frontiers use exactly 12 offer-search pages as their request budget by default.

Usage:
    python scripts/compare_kleinanzeigen_frontiers.py

Only run explicitly with operator permission on a network where public searches
are permitted. Fail closed on 401/403/challenges, bad regions or incomplete cards.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app.sources.base import SourceBatch
from app.sources.property.kleinanzeigen_de import (
    KleinanzeigenGermanyPropertySource,
)
from app.sources.base import RawProperty


def summarize_batches(
    national: list[SourceBatch[RawProperty]],
    regional: list[SourceBatch[RawProperty]],
) -> dict[str, object]:
    national_ids = {item.source_listing_id for batch in national for item in batch.items}
    regional_ids = {item.source_listing_id for batch in regional for item in batch.items}
    return {
        "national": {
            "pages": sum(batch.pages_fetched for batch in national),
            "unique_in_budget": len(national_ids),
        },
        "regional_pilot": {
            "pages": sum(batch.pages_fetched for batch in regional),
            "unique_in_budget": len(regional_ids),
        },
        "in_both": len(national_ids & regional_ids),
        "regional_only": len(regional_ids - national_ids),
        "national_only": len(national_ids - regional_ids),
        "catalog_deactivations": 0,
        "authority": "discovery_only_no_reconciliation",
    }


async def compare(*, delay: float = 3.0) -> dict[str, object]:
    national = KleinanzeigenGermanyPropertySource(
        request_delay_seconds=delay,
        frontier_pages=12,
        hard_max_pages=40,
    )
    regional = KleinanzeigenGermanyPropertySource(
        request_delay_seconds=delay,
        frontier_pages=3,
        hard_max_pages=40,
        regional_pilot=True,
    )
    national_batches = [
        await national.fetch_shard(shard)
        for shard in national.default_shards()
    ]
    regional_batches = [
        await regional.fetch_shard(shard)
        for shard in regional.default_shards()
    ]
    return summarize_batches(national_batches, regional_batches)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()
    if not 2.0 <= args.delay <= 60.0:
        parser.error("--delay must be between 2 and 60 seconds")
    result = asyncio.run(compare(delay=args.delay))
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
