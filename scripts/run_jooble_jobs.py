from __future__ import annotations

import argparse
import asyncio
import os

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.job.jooble import BASE_URL, JoobleJobSource

SOURCE_NAME = "jooble-api-at"
ADAPTER_PATH = "app.sources.job.jooble.JoobleJobSource"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the low-request Austria frontier through Jooble's official REST API."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Minimum delay between API requests (minimum/default: 1 second).",
    )
    parser.add_argument(
        "--results-per-query",
        type=int,
        default=50,
        help="Results requested for each keyword query (default/max: 50).",
    )
    return parser.parse_args()


def get_or_create_source() -> int:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        config = {
            "scope": "Austria jobs from the documented at.jooble.org REST API",
            "acquisition": "official Jooble regional API; five first-page keyword queries",
            "coverage": "intentionally incomplete frontier; never authoritative for disappearance",
            "quota_policy": "five requests/run; free key documented as 500 lifetime requests",
            "reconciliation_interval_hours": None,
            "credentials": "JOOBLE_AT_API_KEY environment variable",
        }
        if source is None:
            source = Source(
                name=SOURCE_NAME,
                category=SourceCategory.JOB,
                adapter=ADAPTER_PATH,
                base_url=BASE_URL,
                enabled=True,
                poll_interval_minutes=1440,
                config=config,
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        else:
            source.adapter = ADAPTER_PATH
            source.base_url = BASE_URL
            source.enabled = True
            source.poll_interval_minutes = 1440
            source.config = config
            session.commit()
        return source.id


async def async_main() -> int:
    args = parse_args()
    api_key = os.environ.get("JOOBLE_AT_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "Missing Jooble Austria API key. Set JOOBLE_AT_API_KEY; its value is never "
            "printed or persisted by this runner."
        )
    if args.results_per_query <= 0:
        raise SystemExit("--results-per-query must be positive")

    source_id = get_or_create_source()
    adapter = JoobleJobSource(
        api_key=api_key,
        request_delay_seconds=max(1.0, args.delay),
        results_per_query=min(50, args.results_per_query),
    )

    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("Jooble source disappeared before the run started")

        run, summary = await run_job_source(
            session,
            source=source,
            adapter=adapter,
            reconciliation=False,
        )

        print(f"Run #{run.id}: {run.mode}")
        print(f"status={summary.run_status} coverage={summary.coverage_status}")
        print(
            "shards="
            f"{summary.shards_completed}/{summary.shards_total} "
            f"failed={summary.shards_failed} api_requests={summary.pages_fetched}"
        )
        print(
            f"seen={summary.items_seen} new={summary.items_new} "
            f"updated={summary.items_updated} source_reported={summary.source_reported_count}"
        )
        print(
            "note=official API frontier is deliberately coverage-incomplete; "
            "it cannot deactivate missing listings"
        )

    return 0 if summary.run_status != "failed" else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
