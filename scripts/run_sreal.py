from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.property_runner import run_property_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.property.sreal_v2 import BASE_URL, SRealPropertySource

ADAPTER_PATH = "app.sources.property.sreal_v2.SRealPropertySource"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Austrian s REAL house-for-sale direct source."
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Scan all currently visible s REAL result pages and reconcile on complete coverage.",
    )
    parser.add_argument(
        "--incremental-pages",
        type=int,
        default=1,
        help="Newest result pages for a normal incremental run (default: 1).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.6,
        help="Base delay between HTTP requests, with jitter (default: 0.6 seconds).",
    )
    parser.add_argument(
        "--hard-max-pages",
        type=int,
        default=100,
        help="Safety ceiling for reconciliation pagination (default: 100 pages).",
    )
    parser.add_argument(
        "--enrich-details",
        action="store_true",
        help="Load s REAL detail pages to enrich description and complete area metadata.",
    )
    return parser.parse_args()


def get_or_create_source() -> Source:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == "sreal.at"))
        if source is None:
            source = Source(
                name="sreal.at",
                category=SourceCategory.PROPERTY,
                adapter=ADAPTER_PATH,
                base_url=BASE_URL,
                enabled=True,
                poll_interval_minutes=60,
                config={
                    "scope": "Austria houses for sale",
                    "acquisition": "public direct broker result pages; minimal metadata retention",
                    "sharding": "nationwide house-buy search",
                    "incremental_pages": 1,
                    "reconciliation_interval_hours": 24,
                },
            )
            session.add(source)
        else:
            source.adapter = ADAPTER_PATH
            source.enabled = True
        session.commit()
        session.refresh(source)
        return source


async def async_main() -> int:
    args = parse_args()
    source = get_or_create_source()
    adapter = SRealPropertySource(
        request_delay_seconds=args.delay,
        incremental_pages=args.incremental_pages,
        hard_max_pages=args.hard_max_pages,
        enrich_details=args.enrich_details,
    )

    with SessionLocal() as session:
        source = session.get(Source, source.id)
        if source is None:
            raise RuntimeError("s REAL source disappeared before the run started")
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
