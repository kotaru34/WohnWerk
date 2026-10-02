from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.property_runner import run_property_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.property.von_poll_de import BASE_URL, VonPollGermanyPropertySource

SOURCE_NAME = "von-poll-de"
ADAPTER_PATH = "app.sources.property.von_poll_de.VonPollGermanyPropertySource"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run VON POLL's public German house-for-sale inventory."
    )
    parser.add_argument("--reconcile", action="store_true")
    parser.add_argument("--incremental-pages", type=int, default=2)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--hard-max-pages", type=int, default=100)
    return parser.parse_args()


def get_or_create_source() -> int:
    config = {
        "country_code": "DE",
        "scope": "VON POLL Germany houses for sale; WohnWerk budget EUR 30,000..200,000",
        "acquisition": (
            "public state house-search pages; no login; unavailable/reserved cards are "
            "observed for coverage but not ingested as active offers"
        ),
        "retention": (
            "source identity/URL, title, price, explicit living/plot area, PLZ/city, "
            "short source-backed heating facts; no contact data or portal-hosted photos"
        ),
        "sharding": "16 Bundeslaender/city-states, public pagination up to 100 pages each",
        "coverage": (
            "authoritative only after every page of every state shard parses below the cap"
        ),
        "rate_policy": "low-rate HTTP with >=2 second jittered spacing and 429/5xx backoff",
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
    adapter = VonPollGermanyPropertySource(
        request_delay_seconds=max(2.0, args.delay),
        incremental_pages=args.incremental_pages,
        hard_max_pages=args.hard_max_pages,
    )
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("VON POLL source disappeared before the run started")
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
            f"failed={summary.shards_failed} skipped={summary.shards_skipped} "
            f"pages={summary.pages_fetched}"
        )
        print(
            f"seen={summary.items_seen} new={summary.items_new} "
            f"updated={summary.items_updated} source_reported={summary.source_reported_count}"
        )
        if args.reconcile and summary.coverage_status != "ok":
            print("disappeared=0 authority=withheld")
        return 0 if summary.run_status != "failed" else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
