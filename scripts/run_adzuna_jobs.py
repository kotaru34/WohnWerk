from __future__ import annotations

import argparse
import asyncio
import os

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.job.adzuna import BASE_URL, AdzunaJobSource

SOURCE_NAME = "adzuna-api-at"
ADAPTER_PATH = "app.sources.job.adzuna.AdzunaJobSource"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the low-request Austria frontier through Adzuna's official API."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.5,
        help="Minimum delay between API requests (minimum/default: 2.5 seconds).",
    )
    parser.add_argument(
        "--results-per-query",
        type=int,
        default=50,
        help="Results requested for each title query (default/max: 50).",
    )
    parser.add_argument(
        "--max-days-old",
        type=int,
        default=30,
        help="Only request ads no older than this many days (default: 30).",
    )
    return parser.parse_args()


def get_or_create_source() -> int:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        config = {
            "scope": "Austria jobs from the documented Adzuna API country=at endpoint",
            "acquisition": "official Adzuna API; five first-page title queries; no advertiser scraping",
            "terms_use": "personal research",
            "attribution": "Adzuna API",
            "coverage": "intentionally incomplete frontier; never authoritative for disappearance",
            "reconciliation_interval_hours": None,
            "credentials": "ADZUNA_APP_ID + ADZUNA_APP_KEY environment variables",
        }
        if source is None:
            source = Source(
                name=SOURCE_NAME,
                category=SourceCategory.JOB,
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
            source.config = config
            session.commit()
        return source.id


async def async_main() -> int:
    args = parse_args()
    app_id = os.environ.get("ADZUNA_APP_ID", "").strip()
    app_key = os.environ.get("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        raise SystemExit(
            "Missing Adzuna API credentials. Set ADZUNA_APP_ID and ADZUNA_APP_KEY; "
            "their values are never printed or persisted by this runner."
        )
    if args.results_per_query <= 0 or args.max_days_old <= 0:
        raise SystemExit("--results-per-query and --max-days-old must be positive")

    source_id = get_or_create_source()
    adapter = AdzunaJobSource(
        app_id=app_id,
        app_key=app_key,
        request_delay_seconds=max(2.5, args.delay),
        results_per_query=min(50, args.results_per_query),
        max_days_old=args.max_days_old,
    )

    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("Adzuna source disappeared before the run started")

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
