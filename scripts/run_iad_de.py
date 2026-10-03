from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.property_runner import run_property_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.property.iad_de import BASE_URL, IadGermanyPropertySource

SOURCE_NAME = "iad-de"
ADAPTER_PATH = "app.sources.property.iad_de.IadGermanyPropertySource"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the bounded public iad Germany house frontier."
    )
    parser.add_argument("--frontier-pages", type=int, default=8)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--hard-max-pages", type=int, default=40)
    return parser.parse_args()


def get_or_create_source() -> int:
    config = {
        "country_code": "DE",
        "scope": (
            "iad Immobilien Agentur Deutschland public house-sale frontier; "
            "local WohnWerk budget EUR 30,000..200,000"
        ),
        "acquisition": (
            "bounded public nationwide house pages; no login, broker contact extraction "
            "or full-description retention"
        ),
        "retention": (
            "iad object ID/URL, title, asking price, visible living/plot area, PLZ/city "
            "and source-backed preview/heating evidence"
        ),
        "coverage": (
            "frontier-only and never authoritative for disappearance; syndicated "
            "duplicates remain separate provenance under conservative canonical dedupe"
        ),
        "rate_policy": "low-rate HTTP with >=2 second jittered spacing and 429/5xx backoff",
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
    if args.frontier_pages <= 0 or args.hard_max_pages <= 0:
        raise SystemExit("--frontier-pages and --hard-max-pages must be positive")

    source_id = get_or_create_source()
    adapter = IadGermanyPropertySource(
        request_delay_seconds=max(2.0, args.delay),
        frontier_pages=args.frontier_pages,
        hard_max_pages=args.hard_max_pages,
    )
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("iad source disappeared before the run started")
        run, summary = await run_property_source(
            session,
            source=source,
            adapter=adapter,
            reconciliation=False,
        )
        print(f"Run #{run.id}: {run.mode}")
        print(f"status={summary.run_status} coverage={summary.coverage_status}")
        print(
            f"pages={summary.pages_fetched} seen={summary.items_seen} "
            f"new={summary.items_new} updated={summary.items_updated} "
            f"source_reported={summary.source_reported_count}"
        )
        print("disappearance_authority=never frontier_only=yes")
        return 0 if summary.run_status != "failed" else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
