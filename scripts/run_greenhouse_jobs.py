from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.jobs.discovery import partition_job_candidates
from app.jobs.tenant_registry import TenantSeed, enabled_tenants, seed_tenants
from app.models import RunStatus, Source, SourceCategory
from app.sources.base import SourceFetchError
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
        "--preflight",
        action="store_true",
        help=(
            "Fetch and classify every bootstrap board without touching the database. "
            "Exit non-zero if any board cannot be read completely."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout per board request in seconds (default: 30).",
    )
    return parser.parse_args()


def _bootstrap_boards() -> list[GreenhouseBoard]:
    return [
        GreenhouseBoard(
            token=seed.tenant_key,
            company=seed.company,
            region=seed.namespace,
        )
        for seed in DEFAULT_TENANTS
    ]


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


async def preflight_boards(*, timeout_seconds: float) -> bool:
    """Validate bootstrap board connectivity and relevance without persistent writes."""
    adapter = GreenhouseJobSource(
        boards=_bootstrap_boards(),
        timeout_seconds=timeout_seconds,
    )
    ok = True

    for shard in adapter.default_shards():
        try:
            batch = await adapter.fetch_shard(shard, reconciliation=True)
            accepted, rejected = partition_job_candidates(batch.items)
            print(
                f"preflight[{shard.key}]=ok "
                f"source_reported={batch.source_reported_count} "
                f"austrian={len(batch.items)} accepted={len(accepted)} rejected={len(rejected)}"
            )
            for item in accepted[:10]:
                gate = (item.raw_payload or {}).get("wohnwerk_discovery_gate") or {}
                print(f"  accepted={item.title} reason={gate.get('reason')}")
        except SourceFetchError as exc:
            ok = False
            print(f"preflight[{shard.key}]=failed error={type(exc).__name__}: {exc}")

    print(f"greenhouse_preflight={'success' if ok else 'failed'}")
    return ok


async def async_main() -> int:
    args = parse_args()

    if args.preflight:
        return 0 if await preflight_boards(timeout_seconds=args.timeout) else 1

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

    # Unlike established frontier sources, every configured Greenhouse board is a
    # complete authoritative shard. Operational callers must therefore treat a
    # partial multi-board run as failure rather than silently enabling degraded data.
    return 0 if summary.run_status == RunStatus.SUCCESS else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
