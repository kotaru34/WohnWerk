from __future__ import annotations

import argparse
import asyncio
import random
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    CoverageStatus,
    CrawlMode,
    CrawlRun,
    CrawlShardRun,
    RunStatus,
    Source,
    SourceShard,
)
from app.sources.property.sreal_v2 import SEARCH_URL, parse_sreal_search_page


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the latest degraded s REAL reconciliation against the listing-ID-driven "
            "search parser and reclassify it only when the historical 314/308-style gap is "
            "fully explained by duplicate detail anchors."
        )
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.35,
        help="Delay between search-page verification requests (default: 0.35 seconds).",
    )
    return parser.parse_args()


async def probe_search_pages(max_page: int, *, delay: float) -> tuple[int, int, int, int]:
    headers = {
        "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian property search)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
    }
    raw_anchors = 0
    cards = 0
    parsed = 0
    metadata_fallbacks = 0

    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30.0) as client:
        for page_number in range(1, max_page + 1):
            if page_number > 1 and delay:
                await asyncio.sleep(delay * random.uniform(0.8, 1.25))
            response = await client.get(f"{SEARCH_URL}?p={page_number}")
            response.raise_for_status()
            page = parse_sreal_search_page(response.text, page_url=str(response.url))
            if page.max_page != max_page:
                raise RuntimeError(
                    f"s REAL pagination changed during verification: "
                    f"expected {max_page}, page {page_number} reports {page.max_page}"
                )
            if page.cards_seen != page.cards_parsed:
                raise RuntimeError(
                    f"listing-ID parser still incomplete on page {page_number}: "
                    f"{page.cards_parsed}/{page.cards_seen}"
                )
            raw_anchors += page.raw_detail_anchors
            cards += page.cards_seen
            parsed += page.cards_parsed
            metadata_fallbacks += page.metadata_fallbacks

    return raw_anchors, cards, parsed, metadata_fallbacks


async def async_main() -> int:
    args = parse_args()

    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == "sreal.at"))
        if source is None:
            raise SystemExit("sreal.at source is not configured")

        run = session.scalar(
            select(CrawlRun)
            .where(
                CrawlRun.source_id == source.id,
                CrawlRun.mode == CrawlMode.RECONCILIATION,
            )
            .order_by(CrawlRun.started_at.desc())
            .limit(1)
        )
        if run is None:
            raise SystemExit("sreal.at has no reconciliation run")
        if run.coverage_status == CoverageStatus.OK:
            print(f"s REAL Run #{run.id} is already coverage=ok")
            return 0

        shard_run = session.scalar(
            select(CrawlShardRun)
            .join(SourceShard, SourceShard.id == CrawlShardRun.shard_id)
            .where(
                CrawlShardRun.crawl_run_id == run.id,
                SourceShard.source_id == source.id,
                SourceShard.key == "austria-houses-buy",
            )
        )
        if shard_run is None:
            raise SystemExit("s REAL reconciliation shard row not found")

        cursor = shard_run.next_cursor or {}
        historical_cards = int(cursor.get("discovery_cards_seen") or 0)
        historical_parsed = int(cursor.get("discovery_cards_parsed") or 0)
        max_page = int(cursor.get("discovery_max_page") or 0)
        detail_attempted = int(cursor.get("detail_enrichment_attempted") or 0)
        detail_succeeded = int(cursor.get("detail_enrichment_succeeded") or 0)
        detail_failed = int(cursor.get("detail_enrichment_failed") or 0)

        if shard_run.status != RunStatus.SUCCESS or shard_run.result_cap_hit:
            raise SystemExit("Refusing reclassification: historical shard was failed or capped")
        if max_page <= 0 or shard_run.pages_fetched != max_page:
            raise SystemExit("Refusing reclassification: historical traversal was incomplete")
        if historical_parsed != run.items_seen:
            raise SystemExit(
                "Refusing reclassification: historical parsed count does not equal persisted seen count"
            )
        if detail_failed or detail_attempted != detail_succeeded or detail_succeeded != run.items_seen:
            raise SystemExit(
                "Refusing reclassification: historical detail enrichment was not complete"
            )

        expected_duplicate_anchor_gap = historical_cards - historical_parsed
        run_id = run.id
        historical_seen = run.items_seen

    raw_anchors, cards, parsed, metadata_fallbacks = await probe_search_pages(
        max_page,
        delay=max(0.0, args.delay),
    )
    duplicate_anchor_gap = raw_anchors - cards

    print(
        f"probe pages={max_page} raw_detail_anchors={raw_anchors} "
        f"unique_cards={cards} materialized={parsed} "
        f"duplicate_anchors={duplicate_anchor_gap} metadata_fallbacks={metadata_fallbacks}"
    )
    print(
        f"historical run={run_id} cards={historical_cards} parsed={historical_parsed} "
        f"seen={historical_seen} gap={expected_duplicate_anchor_gap}"
    )

    if cards != historical_seen:
        raise SystemExit(
            "Refusing reclassification: current unique listing count differs from historical seen count"
        )
    if duplicate_anchor_gap != expected_duplicate_anchor_gap:
        raise SystemExit(
            "Refusing reclassification: duplicate-anchor gap does not explain historical mismatch"
        )
    if parsed != cards:
        raise SystemExit("Refusing reclassification: current listing-ID parser is incomplete")

    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == "sreal.at"))
        run = session.get(CrawlRun, run_id)
        if source is None or run is None:
            raise SystemExit("s REAL source/run disappeared during verification")
        shard_run = session.scalar(
            select(CrawlShardRun).where(CrawlShardRun.crawl_run_id == run.id)
        )
        if shard_run is None:
            raise SystemExit("s REAL shard row disappeared during verification")

        now = datetime.now(UTC)
        shard_run.coverage_complete = True
        run.status = RunStatus.SUCCESS
        run.coverage_status = CoverageStatus.OK
        source.coverage_status = CoverageStatus.OK
        source.last_reconciliation_at = now
        source.last_success_at = now
        session.commit()

    print(
        f"Reclassified s REAL Run #{run_id}: status=success coverage=ok; "
        "no listings were deactivated."
    )
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
