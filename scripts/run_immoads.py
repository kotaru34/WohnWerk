from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.property_runner import run_property_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.property.immoads import BASE_URL, ImmoAdsPropertySource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Austrian ImmoAds house-for-sale source.")
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Scan the complete result set and allow authoritative reconciliation only on OK coverage.",
    )
    parser.add_argument(
        "--incremental-pages",
        type=int,
        default=5,
        help="Newest result pages to scan for a normal incremental run (default: 5).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.65,
        help="Base delay between HTTP requests, with jitter (default: 0.65 seconds).",
    )
    parser.add_argument(
        "--hard-max-pages",
        type=int,
        default=200,
        help="Safety ceiling for a single reconciliation run (default: 200 pages).",
    )
    return parser.parse_args()


def get_or_create_source() -> Source:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == "immoads.at"))
        if source is None:
            source = Source(
                name="immoads.at",
                category=SourceCategory.PROPERTY,
                adapter="app.sources.property.immoads.ImmoAdsPropertySource",
                base_url=BASE_URL,
                enabled=True,
                poll_interval_minutes=30,
                config={
                    "scope": "Austria houses for sale",
                    "acquisition": "public search/detail HTML",
                    "incremental_pages": 5,
                    "reconciliation_interval_hours": 24,
                },
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        return source


async def async_main() -> int:
    args = parse_args()
    source = get_or_create_source()
    adapter = ImmoAdsPropertySource(
        request_delay_seconds=args.delay,
        incremental_pages=args.incremental_pages,
        hard_max_pages=args.hard_max_pages,
    )

    with SessionLocal() as session:
        source = session.get(Source, source.id)
        if source is None:
            raise RuntimeError("ImmoAds source disappeared before the run started")
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


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
