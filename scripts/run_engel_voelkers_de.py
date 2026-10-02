from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.property_runner import run_property_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.property.engel_voelkers_de import (
    BASE_URL,
    EngelVoelkersGermanyPropertySource,
)

SOURCE_NAME = "engel-voelkers-de"
ADAPTER_PATH = (
    "app.sources.property.engel_voelkers_de.EngelVoelkersGermanyPropertySource"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the bounded newest-first Engel & Völkers German house frontier."
    )
    parser.add_argument("--frontier-pages", type=int, default=8)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--hard-max-pages", type=int, default=40)
    return parser.parse_args()


def get_or_create_source() -> int:
    config = {
        "country_code": "DE",
        "scope": (
            "Engel & Völkers public Germany house-sale newest frontier; local WohnWerk "
            "budget EUR 30,000..200,000"
        ),
        "acquisition": (
            "bounded public newest-first result pages; no login, contact extraction, "
            "messages or portal-hosted photo retention"
        ),
        "retention": (
            "source UUID/URL, title, asking price, explicit living/plot area, public "
            "location label and bounded source-backed heating evidence"
        ),
        "coverage": (
            "frontier-only and never authoritative for disappearance; old listings "
            "remain active until another liveness path provides evidence"
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
                poll_interval_minutes=120,
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
    adapter = EngelVoelkersGermanyPropertySource(
        request_delay_seconds=max(2.0, args.delay),
        frontier_pages=args.frontier_pages,
        hard_max_pages=args.hard_max_pages,
    )
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("Engel & Völkers source disappeared before the run started")
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
