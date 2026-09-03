from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.jobs.source_coordinates import apply_source_job_coordinates
from app.models import Source, SourceCategory
from app.sources.job.arbeitsagentur import BASE_URL, ArbeitsagenturJobSource

SOURCE_NAME = "arbeitsagentur-jobsuche-de"
ADAPTER_PATH = "app.sources.job.arbeitsagentur.ArbeitsagenturJobSource"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Germany engineering frontier through BA Jobsuche."
    )
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--max-days-old", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.5)
    return parser.parse_args()


def get_or_create_source() -> int:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        config = {
            "country_code": "DE",
            "scope": "Germany engineering jobs from Bundesagentur Jobsuche title frontiers",
            "acquisition": "public official-frontend Jobsuche endpoint; no account/login required",
            "terms_use": "personal research",
            "coverage": "intentionally incomplete frontier; never authoritative for disappearance",
            "reconciliation_interval_hours": None,
            "auth": "public frontend header X-API-Key=jobboerse-jobsuche",
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
            source.config = {**(source.config or {}), **config}
            session.commit()
        return source.id


async def async_main() -> int:
    args = parse_args()
    if args.page_size <= 0 or args.max_pages <= 0 or args.max_days_old <= 0:
        raise SystemExit("--page-size, --max-pages and --max-days-old must be positive")

    source_id = get_or_create_source()
    adapter = ArbeitsagenturJobSource(
        page_size=min(args.page_size, 100),
        max_pages=args.max_pages,
        max_days_old=min(args.max_days_old, 100),
        request_delay_seconds=max(0.0, args.delay),
    )

    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("Arbeitsagentur source disappeared before the run started")

        run, summary = await run_job_source(
            session,
            source=source,
            adapter=adapter,
            reconciliation=False,
        )
        coordinate_fallbacks = apply_source_job_coordinates(session, source.id)

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
        print(f"source_coordinate_fallbacks={coordinate_fallbacks}")
        print(
            "note=BA endpoint is a public official-frontend interface, not an official developer API; "
            "the source remains coverage-incomplete and cannot deactivate missing listings"
        )

    return 0 if summary.run_status != "failed" else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
