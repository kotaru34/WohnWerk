from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.jobs.tenant_registry import TenantSeed, enabled_tenants, seed_tenants
from app.models import Source, SourceCategory
from app.sources.job.smartrecruiters import SmartRecruitersJobSource, SmartRecruitersSite

ADAPTER_PATH = "app.sources.job.smartrecruiters.SmartRecruitersJobSource"
SOURCE_NAME = "smartrecruiters-public-postings"

DEFAULT_TENANTS = [
    TenantSeed(tenant_key="BekumGroup", company="Bekum Group"),
    TenantSeed(tenant_key="ATParchitekteningenieure", company="ATP architekten ingenieure"),
    TenantSeed(tenant_key="ALTEN", company="ALTEN"),
    TenantSeed(tenant_key="AustroHolding", company="Austro Holding"),
    TenantSeed(tenant_key="BoschGroup", company="Bosch Group"),
    TenantSeed(tenant_key="Brainlab", company="Brainlab / medPhoton"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run registered SmartRecruiters public postings restricted to Austria."
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Traverse all Austrian public postings for every enabled tenant.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Delay before SmartRecruiters API requests (default: 0.2 seconds).",
    )
    return parser.parse_args()


def get_or_create_source() -> int:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        config = {
            "scope": "Austrian public vacancies from registered SmartRecruiters companies",
            "acquisition": "documented public SmartRecruiters Posting API",
            "sharding": "one shard per enabled DB-backed tenant",
            "tenant_registry": "job_source_tenants",
            "country_filter": "at",
            "destination": "PUBLIC",
            "page_size": 100,
            "reconciliation_interval_hours": 24,
        }
        if source is None:
            source = Source(
                name=SOURCE_NAME,
                category=SourceCategory.JOB,
                adapter=ADAPTER_PATH,
                base_url="https://api.smartrecruiters.com/v1/companies/{tenant}/postings",
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


def load_sites(source_id: int) -> list[SmartRecruitersSite]:
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("SmartRecruiters source disappeared before tenant loading")
        tenants = enabled_tenants(session, source=source)
        sites = [SmartRecruitersSite(tenant=row.tenant_key, company=row.company) for row in tenants]
        if not sites:
            raise RuntimeError("No enabled SmartRecruiters tenants are registered")
        return sites


async def async_main() -> int:
    args = parse_args()
    source_id = get_or_create_source()
    adapter = SmartRecruitersJobSource(
        sites=load_sites(source_id),
        request_delay_seconds=args.delay,
    )

    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("SmartRecruiters source disappeared before the run started")

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
