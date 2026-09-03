from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.property_runner import run_property_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.property.immowelt_de import BASE_URL
from app.sources.property.immowelt_de_headed import ImmoweltHeadedPropertySource

SOURCE_NAME = "immowelt-de"
ADAPTER_PATH = "app.sources.property.immowelt_de_headed.ImmoweltHeadedPropertySource"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the public German Immowelt house-for-sale source."
    )
    parser.add_argument("--reconcile", action="store_true")
    parser.add_argument("--incremental-pages", type=int, default=2)
    parser.add_argument("--delay", type=float, default=15.0)
    parser.add_argument("--hard-max-pages", type=int, default=250)
    return parser.parse_args()


def get_or_create_source() -> int:
    config = {
        "country_code": "DE",
        "scope": "Germany houses for sale priced EUR 30,000 through EUR 300,000",
        "acquisition": "public browser-rendered search pages; no detail pages, login or challenge solving",
        "retention": "title, price, area, PLZ, city and source URL only; no contact data or photos",
        "sharding": "16 states/city-states x 3 non-overlapping price bands",
        "ordering": "newest first; incremental shard scheduling is least-recently-successful first",
        "coverage": "authoritative only when every shard is exhaustively parsed below page 250",
        "rate_policy": (
            "low-rate navigation with roughly 15-second jittered spacing; "
            "first HTTP 403 halts further source requests in that run"
        ),
        "runtime": "headed Playwright Chromium on an Xvfb display is required",
        "reconciliation_interval_hours": 24,
    }
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        if source is None:
            source = Source(
                name=SOURCE_NAME,
                category=SourceCategory.PROPERTY,
                adapter=ADAPTER_PATH,
                base_url=BASE_URL,
                enabled=True,
                poll_interval_minutes=180,
                config=config,
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        else:
            source.adapter = ADAPTER_PATH
            source.base_url = BASE_URL
            source.enabled = True
            source.config = {**(source.config or {}), **config}
            session.commit()
        return source.id


async def async_main() -> int:
    args = parse_args()
    if args.incremental_pages <= 0 or args.hard_max_pages <= 0:
        raise SystemExit("--incremental-pages and --hard-max-pages must be positive")

    source_id = get_or_create_source()
    adapter = ImmoweltHeadedPropertySource(
        request_delay_seconds=max(1.0, args.delay),
        incremental_pages=args.incremental_pages,
        hard_max_pages=args.hard_max_pages,
    )
    try:
        with SessionLocal() as session:
            source = session.get(Source, source_id)
            if source is None:
                raise RuntimeError("Immowelt DE source disappeared before the run started")
            run, summary = await run_property_source(
                session,
                source=source,
                adapter=adapter,
                reconciliation=args.reconcile,
            )

            print(f"Run #{run.id}: {run.mode}")
            print(f"status={summary.run_status} coverage={summary.coverage_status}")
            print(
                "shards="
                f"{summary.shards_completed}/{summary.shards_total} "
                f"failed={summary.shards_failed} pages={summary.pages_fetched}"
            )
            print(
                f"seen={summary.items_seen} new={summary.items_new} "
                f"updated={summary.items_updated} source_reported={summary.source_reported_count}"
            )
            if args.reconcile:
                print(f"disappeared={run.items_disappeared}")
        return 0 if summary.run_status != "failed" else 1
    finally:
        await adapter.aclose()


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
