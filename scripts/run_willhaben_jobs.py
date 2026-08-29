from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.job.willhaben_jobs import BASE_URL, WillhabenJobSource

SOURCE_NAME = "willhaben-jobs"
ADAPTER_PATH = "app.sources.job.willhaben_jobs.WillhabenJobSource"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Low-impact willhaben Jobs frontier: five first-page searches with bounded "
            "detail enrichment for mechanically relevant titles."
        )
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Minimum delay between source requests (default: 1.0s).",
    )
    return parser.parse_args()


def get_or_create_source() -> int:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        config = {
            "scope": "focused Austrian mechanical-engineering searches on willhaben Jobs",
            "acquisition": "first-page search cards plus bounded relevant-detail enrichment",
            "coverage": "intentionally incomplete frontier; never authoritative for disappearance",
            "reconciliation_interval_hours": None,
            "detail_policy": "up to 8 mechanically relevant detail pages per search shard",
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
    source_id = get_or_create_source()
    adapter = WillhabenJobSource(request_delay_seconds=max(0.0, args.delay))

    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("willhaben Jobs source disappeared before the run started")

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
            f"failed={summary.shards_failed} requests={summary.pages_fetched}"
        )
        print(
            f"seen={summary.items_seen} new={summary.items_new} "
            f"updated={summary.items_updated} source_reported={summary.source_reported_count}"
        )
        print(
            "note=first-page frontier with bounded relevant-detail enrichment; "
            "no disappearance authority"
        )

    return 0 if summary.run_status != "failed" else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
