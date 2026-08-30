from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.jobs.tenant_registry import TenantSeed, enabled_tenants, seed_tenants
from app.models import Source, SourceCategory
from app.sources.job.greenhouse import GLOBAL_API_BASE, GreenhouseBoard, GreenhouseJobSource

ADAPTER_PATH = "app.sources.job.greenhouse.GreenhouseJobSource"
SOURCE_NAME = "greenhouse-public-job-board"

# Small production bootstrap set: every board below has current public Austrian vacancies.
# The discovery gate still decides professional relevance; this list only grants source coverage.
DEFAULT_TENANTS = [
    TenantSeed(tenant_key="gropyus", company="GROPYUS", namespace="eu"),
    TenantSeed(tenant_key="planetlabs", company="Planet", namespace="global"),
    TenantSeed(tenant_key="bitpanda", company="Bitpanda", namespace="global"),
    TenantSeed(tenant_key="ketryx", company="Ketryx", namespace="global"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run registered Greenhouse public job boards and retain Austrian vacancies."
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Treat every successful complete board response as authoritative for that shard.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout per board request in seconds (default: 30).",
    )
    return parser.parse_args()


def get_or_create_source() -> int:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        config = {
            "scope": "Austrian vacancies from registered Greenhouse public job boards",
            "acquisition": "public Greenhouse Job Board API; published postings only",
            "sharding": "one shard per enabled DB-backed employer board",
            "tenant_registry": "job_source_tenants",
            "reconciliation_interval_hours": 24,
        }
        if source is None:
            source = Source(
                name=SOURCE_NAME,
                category=SourceCategory.JOB,
                adapter=ADAPTER_PATH,
                base_url=GLOBAL_API_BASE,
                enabled=True,
                poll_interval_minutes=120,
                config=config,
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        else:
            source.adapter = ADAPTER_PATH
            source.enabled = True
            source.config = config
            session.commit()

        seed_tenants(session, source=source, seeds=DEFAULT_TENANTS)
        return source.id


def load_boards(source_id: int) -> list[GreenhouseBoard]:
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("Greenhouse source disappeared before tenant loading")
        rows = enabled_tenants(session, source=source)
        boards = [
            GreenhouseBoard(
                token=row.tenant_key,
                company=row.company,
                region=row.namespace,
            )
            for row in rows
        ]
        if not boards:
            raise RuntimeError("No enabled Greenhouse boards are registered")
        return boards


async def async_main() -> int:
    args = parse_args()
    source_id = get_or_create_source()
    adapter = GreenhouseJobSource(
        boards=load_boards(source_id),
        timeout_seconds=args.timeout,
    )

    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("Greenhouse source disappeared before the run started")
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

    return 0 if summary.run_status != "failed" else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
