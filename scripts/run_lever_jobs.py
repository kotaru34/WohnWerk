from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.jobs.discovery import partition_job_candidates
from app.jobs.tenant_registry import TenantSeed, enabled_tenants, seed_tenants
from app.models import CoverageStatus, RunStatus, Source, SourceCategory
from app.sources.base import SourceFetchError
from app.sources.job.lever import GLOBAL_API_BASE, LeverJobSource, LeverSite

ADAPTER_PATH = "app.sources.job.lever.LeverJobSource"
SOURCE_NAME = "lever-public-postings"

DEFAULT_TENANTS = [
    TenantSeed(tenant_key="blackshark", company="Blackshark.ai", namespace="eu"),
    TenantSeed(tenant_key="westernacher", company="Westernacher Consulting", namespace="eu"),
    TenantSeed(tenant_key="cargo-partner", company="cargo-partner", namespace="global"),
    TenantSeed(tenant_key="qualysoft", company="Qualysoft", namespace="global"),
    TenantSeed(tenant_key="tsmg", company="TSMG", namespace="global"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run registered Lever public-posting feeds and retain Austrian vacancies."
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Traverse each enabled tenant feed to completion and reconcile complete shards.",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "Fetch and classify every bootstrap tenant without touching the database. "
            "Exit non-zero if any tenant cannot be read to completion."
        ),
    )
    parser.add_argument(
        "--incremental-pages",
        type=int,
        default=1,
        help="Newest pages per tenant for a normal incremental run (default: 1).",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Lever Postings API page size (default: 100).",
    )
    parser.add_argument(
        "--hard-max-pages",
        type=int,
        default=100,
        help="Safety ceiling per tenant during reconciliation (default: 100).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="Delay between pages from the same tenant (default: 0.25 seconds).",
    )
    return parser.parse_args()


def _bootstrap_sites() -> list[LeverSite]:
    return [
        LeverSite(
            site=seed.tenant_key,
            company=seed.company,
            region=seed.namespace,
        )
        for seed in DEFAULT_TENANTS
    ]


def get_or_create_source() -> int:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        config = {
            "scope": "Austrian vacancies from registered Lever tenants",
            "acquisition": "documented public Lever Postings API; published postings only",
            "sharding": "one shard per enabled DB-backed tenant",
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
                poll_interval_minutes=60,
                config=config,
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        else:
            source.adapter = ADAPTER_PATH
            # Preserve an explicit operator disable. Running the script manually must not
            # silently re-enable a source that was taken out of scheduler rotation.
            source.config = config
            session.commit()

        seed_tenants(session, source=source, seeds=DEFAULT_TENANTS)
        return source.id


def load_sites(source_id: int) -> list[LeverSite]:
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("Lever public-postings source disappeared before tenant loading")
        rows = enabled_tenants(session, source=source)
        sites = [
            LeverSite(
                site=row.tenant_key,
                company=row.company,
                region=row.namespace,
            )
            for row in rows
        ]
        if not sites:
            raise RuntimeError("No enabled Lever tenants are registered")
        return sites


async def preflight_sites(
    *,
    page_size: int,
    hard_max_pages: int,
    delay: float,
) -> bool:
    """Validate bootstrap tenant connectivity and discovery yield without persistent writes."""
    adapter = LeverJobSource(
        sites=_bootstrap_sites(),
        request_delay_seconds=delay,
        incremental_pages=1,
        page_size=page_size,
        hard_max_pages=hard_max_pages,
    )
    ok = True

    for shard in adapter.default_shards():
        try:
            batch = await adapter.fetch_shard(shard, reconciliation=True)
            if not batch.coverage_complete or batch.result_cap_hit:
                ok = False
                print(
                    f"preflight[{shard.key}]=failed "
                    f"error=incomplete_coverage pages={batch.pages_fetched} "
                    f"austrian={len(batch.items)} cap={batch.result_cap_hit}"
                )
                continue

            accepted, rejected = partition_job_candidates(batch.items)
            print(
                f"preflight[{shard.key}]=ok "
                f"source_reported={batch.source_reported_count} "
                f"austrian={len(batch.items)} accepted={len(accepted)} "
                f"rejected={len(rejected)} pages={batch.pages_fetched}"
            )
            for item in accepted[:20]:
                gate = (item.raw_payload or {}).get("wohnwerk_discovery_gate") or {}
                print(
                    f"  accepted={item.title} "
                    f"reason={gate.get('reason')} url={item.url}"
                )
        except SourceFetchError as exc:
            ok = False
            print(f"preflight[{shard.key}]=failed error={type(exc).__name__}: {exc}")

    print(f"lever_preflight={'success' if ok else 'failed'}")
    return ok


async def async_main() -> int:
    args = parse_args()

    if args.preflight:
        return (
            0
            if await preflight_sites(
                page_size=args.page_size,
                hard_max_pages=args.hard_max_pages,
                delay=args.delay,
            )
            else 1
        )

    source_id = get_or_create_source()
    adapter = LeverJobSource(
        sites=load_sites(source_id),
        request_delay_seconds=args.delay,
        incremental_pages=args.incremental_pages,
        page_size=args.page_size,
        hard_max_pages=args.hard_max_pages,
    )

    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("Lever public-postings source disappeared before the run started")
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
