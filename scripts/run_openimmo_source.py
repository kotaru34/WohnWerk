from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.property_runner import run_property_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.property.openimmo import OpenImmoFeedPropertySource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest an authorized OpenImmo property feed")
    parser.add_argument("--name", required=True, help="Stable WohnWerk source name")
    parser.add_argument("--url", required=True, help="OpenImmo XML or ZIP feed URL")
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Treat this as a complete source snapshot and deactivate missing source listings",
    )
    return parser.parse_args()


async def run() -> None:
    args = parse_args()
    adapter = OpenImmoFeedPropertySource(name=args.name, feed_url=args.url)

    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == args.name))
        if source is None:
            source = Source(
                name=args.name,
                category=SourceCategory.PROPERTY,
                adapter="app.sources.property.openimmo.OpenImmoFeedPropertySource",
                base_url=args.url,
                config={"feed_type": "openimmo"},
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        else:
            source.base_url = args.url
            session.commit()

        crawl_run, summary = await run_property_source(
            session,
            source=source,
            adapter=adapter,
            reconciliation=args.reconcile,
        )

    print(
        f"run={crawl_run.id} status={summary.run_status} coverage={summary.coverage_status} "
        f"seen={summary.items_seen} new={summary.items_new} updated={summary.items_updated}"
    )


if __name__ == "__main__":
    asyncio.run(run())
