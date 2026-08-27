from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.job.karriere_at import BASE_URL, KarriereAtJobSource

SOURCE_NAME = "karriere.at"
ADAPTER_PATH = "app.sources.job.karriere_at.KarriereAtJobSource"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Low-impact karriere.at discovery frontier: first result page per focused "
            "search, then details only for title-level candidates."
        )
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.65,
        help="Minimum delay between HTTP requests across the whole run (default: 0.65s).",
    )
    parser.add_argument(
        "--max-details-per-query",
        type=int,
        default=8,
        help="Maximum detail pages opened for one search shard (default: 8).",
    )
    return parser.parse_args()


def get_or_create_source() -> int:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        config = {
            "scope": "focused Austrian engineering searches on public karriere.at pages",
            "acquisition": (
                "low-impact first-page search frontier; detail only after title prefilter"
            ),
            "coverage": (
                "intentionally incomplete discovery frontier; never authoritative for disappearance"
            ),
            "reconciliation_interval_hours": None,
            "detail_policy": "title candidate first, detail page second",
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
    if args.max_details_per_query <= 0:
        raise SystemExit("--max-details-per-query must be positive")

    source_id = get_or_create_source()
    adapter = KarriereAtJobSource(
        request_delay_seconds=max(0.0, args.delay),
        max_details_per_shard=args.max_details_per_query,
    )

    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("karriere.at source disappeared before the run started")

        # This source is intentionally a frontier scan for now, not a complete
        # board traversal. Never present it to lifecycle reconciliation as complete.
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
            "note=frontier scan is deliberately coverage-incomplete; "
            "it cannot deactivate missing listings"
        )

    return 0 if summary.run_status != "failed" else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
