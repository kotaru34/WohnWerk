from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.jobs.discovery import classify_job_candidate
from app.jobs.tenant_registry import TenantSeed, enabled_tenants, seed_tenants
from app.models import CoverageStatus, RunStatus, Source, SourceCategory
from app.sources.base import SourceFetchError
from app.sources.job.successfactors import SuccessFactorsJobSource, SuccessFactorsSite

ADAPTER_PATH = "app.sources.job.successfactors.SuccessFactorsJobSource"
SOURCE_NAME = "successfactors-public-career-site"

DEFAULT_TENANTS = [
    TenantSeed(
        tenant_key="andritz-professionals",
        company="ANDRITZ",
        enabled=False,
        config={
            "origin": "https://careers.andritz.com",
            "search_path": "/go/Professionals/924202",
            "page_size": 25,
            "candidate_evidence": (
                "ANDRITZ public Professionals microsite contains Austrian mechanical, "
                "plant-engineering, commissioning and technical project roles"
            ),
        },
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run selected public SAP SuccessFactors career microsites."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--preflight",
        action="store_true",
        help="Fetch and classify built-in candidate sites without touching the database.",
    )
    group.add_argument(
        "--seed",
        action="store_true",
        help="Create the disabled source and candidate tenant rows only.",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Run a complete authoritative scan of enabled career microsites.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.15,
        help="Delay before SuccessFactors requests (default: 0.15 seconds).",
    )
    parser.add_argument(
        "--hard-max-pages",
        type=int,
        default=100,
        help="Safety ceiling for search pages per tenant (default: 100).",
    )
    return parser.parse_args()


def _site_from_seed(seed: TenantSeed) -> SuccessFactorsSite:
    config = seed.config
    origin = config.get("origin")
    search_path = config.get("search_path")
    page_size = config.get("page_size", 25)
    if not isinstance(origin, str) or not isinstance(search_path, str):
        raise TypeError(f"Invalid SuccessFactors seed config for {seed.tenant_key!r}")
    if not isinstance(page_size, int):
        raise TypeError(f"Invalid SuccessFactors page size for {seed.tenant_key!r}")
    return SuccessFactorsSite(
        tenant=seed.tenant_key,
        company=seed.company,
        origin=origin,
        search_path=search_path,
        page_size=page_size,
    )


def get_or_create_source() -> int:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        config = {
            "scope": "Selected employer-owned public SAP SuccessFactors career microsites",
            "acquisition": "public employer career pages; no authenticated or private endpoints",
            "sharding": "one authoritative shard per enabled employer microsite",
            "tenant_registry": "job_source_tenants",
            "reconciliation_interval_hours": 24,
        }
        if source is None:
            source = Source(
                name=SOURCE_NAME,
                category=SourceCategory.JOB,
                adapter=ADAPTER_PATH,
                base_url="https://{employer}/go/{microsite}",
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

        seed_tenants(session, source=source, seeds=DEFAULT_TENANTS)
        return source.id


def load_sites(source_id: int) -> list[SuccessFactorsSite]:
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("SuccessFactors source disappeared before tenant loading")
        rows = enabled_tenants(session, source=source)
        sites = [
            _site_from_seed(
                TenantSeed(
                    tenant_key=row.tenant_key,
                    company=row.company,
                    namespace=row.namespace,
                    config=dict(row.config or {}),
                    enabled=row.enabled,
                )
            )
            for row in rows
        ]
        if not sites:
            raise RuntimeError("No enabled SuccessFactors tenants are registered")
        return sites


async def _preflight(*, delay: float, hard_max_pages: int) -> int:
    failures = 0
    for seed in DEFAULT_TENANTS:
        site = _site_from_seed(seed)
        adapter = SuccessFactorsJobSource(
            sites=[site],
            request_delay_seconds=delay,
            hard_max_pages=hard_max_pages,
        )
        shard = adapter.default_shards()[0]
        try:
            batch = await adapter.fetch_shard(shard, reconciliation=True)
        except (SourceFetchError, TypeError, ValueError, RuntimeError) as exc:
            failures += 1
            print(
                f"preflight[{site.tenant}]=failed "
                f"error={type(exc).__name__}: {exc}"
            )
            continue

        if not batch.coverage_complete or batch.result_cap_hit:
            failures += 1
            print(
                f"preflight[{site.tenant}]=failed error=incomplete_coverage "
                f"source_reported={batch.source_reported_count} "
                f"austrian={len(batch.items)} pages={batch.pages_fetched} "
                f"cap={batch.result_cap_hit}"
            )
            continue

        accepted = []
        rejected = []
        for job in batch.items:
            decision = classify_job_candidate(job)
            (accepted if decision.accepted else rejected).append((job, decision))

        print(
            f"preflight[{site.tenant}]=ok "
            f"source_reported={batch.source_reported_count} "
            f"austrian={len(batch.items)} accepted={len(accepted)} "
            f"rejected={len(rejected)} pages={batch.pages_fetched}"
        )
        for job, decision in accepted:
            print(
                f"  ACCEPT title={job.title!r} "
                f"locations={[row.location_text for row in job.locations]!r} "
                f"reason={decision.reason} url={job.url}"
            )
        for job, decision in rejected[:25]:
            print(f"  reject title={job.title!r} reason={decision.reason}")
        if len(rejected) > 25:
            print(f"  ... {len(rejected) - 25} more rejected")

    print(f"successfactors_preflight_failures={failures}")
    return 0 if failures == 0 else 1


async def async_main() -> int:
    args = parse_args()
    if args.preflight:
        return await _preflight(delay=args.delay, hard_max_pages=args.hard_max_pages)

    source_id = get_or_create_source()
    if args.seed:
        print(f"successfactors_source_id={source_id}")
        print("successfactors_seed=success")
        return 0

    adapter = SuccessFactorsJobSource(
        sites=load_sites(source_id),
        request_delay_seconds=args.delay,
        hard_max_pages=args.hard_max_pages,
    )
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("SuccessFactors source disappeared before the run started")
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
