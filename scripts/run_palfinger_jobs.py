from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.jobs.discovery import classify_job_candidate
from app.jobs.salary import enrich_raw_job_salary
from app.models import CoverageStatus, RunStatus, Source, SourceCategory
from app.sources.base import SourceFetchError
from app.sources.job.palfinger import BASE_URL, PalfingerJobSource

ADAPTER_PATH = "app.sources.job.palfinger.PalfingerJobSource"
SOURCE_NAME = "palfinger-direct-careers"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PALFINGER's public Austrian employer-owned career pages."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--preflight",
        action="store_true",
        help="Fetch and classify PALFINGER Austria without touching the database.",
    )
    group.add_argument(
        "--seed",
        action="store_true",
        help="Create the disabled source row only.",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Run a complete authoritative PALFINGER Austria scan.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.10,
        help="Delay before PALFINGER requests (default: 0.10 seconds).",
    )
    parser.add_argument(
        "--hard-max-pages",
        type=int,
        default=20,
        help="Safety ceiling for Austrian listing pages (default: 20).",
    )
    return parser.parse_args()


def get_or_create_source() -> int:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        config = {
            "scope": "PALFINGER public Austrian employer-owned career pages",
            "acquisition": "public paginated HTML listing and public job detail pages",
            "sharding": "single authoritative Austria career-list shard",
            "reconciliation_interval_hours": 24,
        }
        if source is None:
            source = Source(
                name=SOURCE_NAME,
                category=SourceCategory.JOB,
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
            merged = dict(source.config or {})
            for key, value in config.items():
                merged.setdefault(key, value)
            source.config = merged
            session.commit()
        return source.id


async def _preflight(*, delay: float, hard_max_pages: int) -> int:
    adapter = PalfingerJobSource(
        request_delay_seconds=delay,
        hard_max_pages=hard_max_pages,
    )
    shard = adapter.default_shards()[0]
    try:
        batch = await adapter.fetch_shard(shard, reconciliation=True)
    except (SourceFetchError, TypeError, ValueError, RuntimeError) as exc:
        print(f"palfinger_preflight=failed error={type(exc).__name__}: {exc}")
        return 1

    accepted = []
    rejected = []
    salary_parsed = 0
    for job in batch.items:
        salary_parsed += int(enrich_raw_job_salary(job))
        decision = classify_job_candidate(job)
        (accepted if decision.accepted else rejected).append((job, decision))

    cursor = batch.next_cursor or {}
    print(
        "palfinger_preflight=ok "
        f"source_reported={batch.source_reported_count} "
        f"austrian={len(batch.items)} accepted={len(accepted)} "
        f"rejected={len(rejected)} salary_parsed={salary_parsed} "
        f"pages={batch.pages_fetched} "
        f"listing_pages={cursor.get('listing_pages_fetched')} "
        f"expected_pages={cursor.get('listing_expected_pages')} "
        f"coverage_complete={batch.coverage_complete} "
        f"pagination_failed={cursor.get('pagination_failed')} "
        f"detail_failed={cursor.get('detail_failed', 0)}"
    )
    for job, decision in accepted:
        print(
            f"  ACCEPT title={job.title!r} "
            f"locations={[row.location_text for row in job.locations]!r} "
            f"salary_min={job.salary_min!r} salary_period={job.salary_period!r} "
            f"reason={decision.reason} url={job.url}"
        )
    for job, decision in rejected:
        print(
            f"  reject title={job.title!r} "
            f"reason={decision.reason} url={job.url}"
        )

    if not batch.coverage_complete or batch.result_cap_hit:
        print("palfinger_preflight=review_required reason=incomplete_coverage")
        return 1
    print("palfinger_preflight_failures=0")
    return 0


async def async_main() -> int:
    args = parse_args()
    if args.preflight:
        return await _preflight(
            delay=args.delay,
            hard_max_pages=max(1, args.hard_max_pages),
        )

    source_id = get_or_create_source()
    if args.seed:
        print(f"palfinger_source_id={source_id}")
        print("palfinger_seed=success")
        return 0

    adapter = PalfingerJobSource(
        request_delay_seconds=args.delay,
        hard_max_pages=max(1, args.hard_max_pages),
    )
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("PALFINGER source disappeared before the run started")
        run, summary = await run_job_source(
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
            f"failed={summary.shards_failed} pages={summary.pages_fetched}"
        )
        print(
            f"seen={summary.items_seen} new={summary.items_new} "
            f"updated={summary.items_updated} source_reported={summary.source_reported_count}"
        )
        if args.reconcile:
            print(f"disappeared={run.items_disappeared}")

    if summary.run_status != RunStatus.SUCCESS:
        return 1
    if args.reconcile and summary.coverage_status != CoverageStatus.OK:
        return 1
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
