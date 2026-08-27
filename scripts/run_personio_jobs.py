from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.jobs.location_resolution import canonicalize_locality
from app.jobs.tenant_registry import TenantSeed, enabled_tenants, seed_tenants
from app.models import PostalCode, Source, SourceCategory
from app.sources.job.personio import PERSONIO_BASE_SUFFIX, PersonioJobSource, PersonioSite

ADAPTER_PATH = "app.sources.job.personio.PersonioJobSource"
SOURCE_NAME = "personio-public-xml"

DEFAULT_TENANTS = [
    TenantSeed(tenant_key="easelink-gmbh", company="Easelink GmbH"),
    TenantSeed(tenant_key="axess-ag", company="Axess AG"),
    TenantSeed(tenant_key="isoplus-fwt-aut", company="ISOPLUS Fernwärmetechnik GmbH"),
    TenantSeed(tenant_key="lcm", company="Linz Center of Mechatronics GmbH"),
    TenantSeed(tenant_key="denzel-gruppe", company="DENZEL Gruppe"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run registered public Personio XML feeds and retain Austrian vacancies."
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Mark this complete feed scan as a reconciliation run.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="Delay before each tenant request (default: 0.25 seconds).",
    )
    return parser.parse_args()


def get_or_create_source() -> int:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        config = {
            "scope": "Austrian vacancies from registered Personio career sites",
            "acquisition": "documented public Personio career-site XML feed",
            "sharding": "one shard per enabled DB-backed tenant",
            "tenant_registry": "job_source_tenants",
            "feed_path": "/xml?language=de",
            "reconciliation_interval_hours": 24,
        }
        if source is None:
            source = Source(
                name=SOURCE_NAME,
                category=SourceCategory.JOB,
                adapter=ADAPTER_PATH,
                base_url=f"https://{{tenant}}{PERSONIO_BASE_SUFFIX}/xml",
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


def load_runtime(source_id: int) -> tuple[list[PersonioSite], set[str]]:
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("Personio source disappeared before tenant loading")

        tenants = enabled_tenants(session, source=source)
        sites = [PersonioSite(tenant=row.tenant_key, company=row.company) for row in tenants]
        if not sites:
            raise RuntimeError("No enabled Personio tenants are registered")

        locality_names = set(session.scalars(select(PostalCode.name)))
        localities = {
            canonical
            for value in locality_names
            if (canonical := canonicalize_locality(value)) is not None
        }
        if not localities:
            raise RuntimeError("No Austrian postal localities are loaded")
        return sites, localities


async def async_main() -> int:
    args = parse_args()
    source_id = get_or_create_source()
    sites, localities = load_runtime(source_id)
    adapter = PersonioJobSource(
        sites=sites,
        austrian_localities=localities,
        request_delay_seconds=args.delay,
    )

    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("Personio source disappeared before the run started")

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
