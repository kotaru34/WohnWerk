from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.property_runner import run_property_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.property.remax_de import BASE_URL, RemaxGermanyPropertySource

SOURCE_NAME = "remax-de"
ADAPTER_PATH = "app.sources.property.remax_de.RemaxGermanyPropertySource"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run bounded public RE/MAX Germany state house frontiers."
    )
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--hard-max-cards", type=int, default=80)
    return parser.parse_args()


def get_or_create_source() -> int:
    config = {
        "country_code": "DE",
        "scope": (
            "RE/MAX Germany public state house frontiers; local WohnWerk budget "
            "EUR 30,000..200,000"
        ),
        "acquisition": (
            "one bounded public house-search page per Bundesland/city-state; "
            "no login, contact extraction or bulk detail crawl"
        ),
        "retention": (
            "RE/MAX source object ID/URL, title, asking price, visible living area, "
            "PLZ/city and source-backed preview/heating evidence"
        ),
        "coverage": (
            "frontier-only and never authoritative for disappearance; result counts "
            "are telemetry, not reconciliation authority"
        ),
        "rate_policy": "low-rate HTTP with >=2 second jittered spacing and 429/5xx backoff",
        "operational_status": "production_turnstile_blocked",
        "scheduling": "disabled fail-closed; no challenge bypass",
    }
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        if source is None:
            source = Source(
                name=SOURCE_NAME,
                category=SourceCategory.PROPERTY,
                adapter=ADAPTER_PATH,
                base_url=BASE_URL,
                enabled=False,
                poll_interval_minutes=180,
                config=config,
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        else:
            source.adapter = ADAPTER_PATH
            source.base_url = BASE_URL
            source.enabled = False
            source.config = {**(source.config or {}), **config}
            session.commit()
        return source.id


async def async_main() -> int:
    args = parse_args()
    if args.hard_max_cards <= 0:
        raise SystemExit("--hard-max-cards must be positive")

    source_id = get_or_create_source()
    adapter = RemaxGermanyPropertySource(
        request_delay_seconds=max(2.0, args.delay),
        hard_max_cards=args.hard_max_cards,
    )
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("RE/MAX source disappeared before the run started")
        run, summary = await run_property_source(
            session,
            source=source,
            adapter=adapter,
            reconciliation=False,
        )
        print(f"Run #{run.id}: {run.mode}")
        print(f"status={summary.run_status} coverage={summary.coverage_status}")
        print(
            f"shards={summary.shards_completed}/{summary.shards_total} "
            f"failed={summary.shards_failed} skipped={summary.shards_skipped} "
            f"pages={summary.pages_fetched}"
        )
        print(
            f"seen={summary.items_seen} new={summary.items_new} "
            f"updated={summary.items_updated} source_reported={summary.source_reported_count}"
        )
        print("disappearance_authority=never frontier_only=yes")
        return 0 if summary.run_status != "failed" else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
