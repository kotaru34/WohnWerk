from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.job.stepstone_at import BASE_URL
from app.sources.job.stepstone_salary import StepStoneAtJobSource

SOURCE_NAME = "stepstone.at"
ADAPTER_PATH = "app.sources.job.stepstone_salary.StepStoneAtJobSource"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Low-impact StepStone Austria discovery frontier: five search pages with salary "
            "detail enrichment for discovery-accepted vacancies that still lack salary."
        )
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Minimum delay between requests (default: 1.0s).",
    )
    parser.add_argument(
        "--max-details",
        type=int,
        default=0,
        help=(
            "Optional cap on accepted salary detail pages per shard; 0 enriches every "
            "accepted salary-missing first-page vacancy (default: 0)."
        ),
    )
    return parser.parse_args()


def get_or_create_source() -> int:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        config = {
            "scope": "focused Austrian mechanical-engineering searches on StepStone Austria",
            "acquisition": "first-page search cards plus accepted salary-missing detail pages",
            "coverage": "intentionally incomplete discovery frontier",
            "reconciliation_interval_hours": None,
            "detail_policy": (
                "all discovery-accepted first-page vacancies without usable salary evidence"
            ),
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
    adapter = StepStoneAtJobSource(
        request_delay_seconds=max(0.0, args.delay),
        max_details_per_shard=(args.max_details if args.max_details > 0 else None),
    )

    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("stepstone.at source disappeared before the run started")

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
            "note=first-page frontier with accepted salary-missing detail enrichment; "
            "no disappearance authority"
        )

    return 0 if summary.run_status != "failed" else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
