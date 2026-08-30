from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.job_runner import run_job_source
from app.database import SessionLocal
from app.jobs.discovery import classify_job_candidate
from app.jobs.location_resolution import canonicalize_locality
from app.jobs.tenant_registry import TenantSeed, enabled_tenants, seed_tenants
from app.models import PostalCode, Source, SourceCategory
from app.sources.job.workday import WorkdayJobSource, WorkdaySite

ADAPTER_PATH = "app.sources.job.workday.WorkdayJobSource"
SOURCE_NAME = "workday-public-cxs"

DEFAULT_TENANTS = [
    TenantSeed(
        tenant_key="kiongroup:KIONGroup",
        company="KION Group / Linde Material Handling",
        enabled=False,
        config={
            "origin": "https://kiongroup.wd3.myworkdayjobs.com",
            "tenant": "kiongroup",
            "site": "KIONGroup",
            "locale": "de-DE",
            "search_texts": [
                "Austria",
                "Österreich",
                "Linz",
                "Wiener Neudorf",
                "Dobl",
                "Hohenems",
            ],
            "candidate_evidence": "Austrian intralogistics, commissioning and mechanical roles",
        },
    ),
    TenantSeed(
        tenant_key="magna:Magna",
        company="Magna",
        enabled=False,
        config={
            "origin": "https://magna.wd3.myworkdayjobs.com",
            "tenant": "magna",
            "site": "Magna",
            "locale": "de-DE",
            "search_texts": [
                "Austria",
                "Österreich",
                "St. Valentin",
                "Graz",
                "Wien",
                "Vienna",
            ],
            "candidate_evidence": "Austrian automotive engineering and technical project roles",
        },
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Austrian Workday public CXS search frontiers."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--preflight",
        action="store_true",
        help="Fetch built-in candidate boards without any DB writes.",
    )
    group.add_argument(
        "--seed",
        action="store_true",
        help="Create the disabled Workday source and candidate tenant rows only.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.15,
        help="Delay before Workday requests (default: 0.15 seconds).",
    )
    return parser.parse_args()


def _localities() -> set[str]:
    with SessionLocal() as session:
        names = set(session.scalars(select(PostalCode.name)))
    result = {
        canonical
        for value in names
        if (canonical := canonicalize_locality(value)) is not None
    }
    if not result:
        raise RuntimeError("No Austrian postal localities are loaded")
    return result


def _site_from_seed(seed: TenantSeed) -> WorkdaySite:
    config = seed.config
    origin = config.get("origin")
    tenant = config.get("tenant")
    site = config.get("site")
    locale = config.get("locale", "en-US")
    search_texts = config.get("search_texts")
    if not all(isinstance(value, str) for value in (origin, tenant, site, locale)):
        raise TypeError(f"Invalid Workday seed config for {seed.tenant_key!r}")
    if not isinstance(search_texts, list) or not all(
        isinstance(value, str) and value.strip() for value in search_texts
    ):
        raise TypeError(f"Invalid Workday search_texts for {seed.tenant_key!r}")
    return WorkdaySite(
        tenant=tenant,
        site=site,
        company=seed.company,
        origin=origin,
        locale=locale,
        search_texts=tuple(search_texts),
    )


def get_or_create_source() -> int:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        config = {
            "scope": "Austrian jobs discovered through explicit Workday CXS search frontiers",
            "acquisition": "public unauthenticated Workday Candidate Experience Service JSON",
            "sharding": "one shard per tenant and Austrian frontier query",
            "tenant_registry": "job_source_tenants",
            "coverage_authority": "none; query union is discovery-only",
        }
        if source is None:
            source = Source(
                name=SOURCE_NAME,
                category=SourceCategory.JOB,
                adapter=ADAPTER_PATH,
                base_url="https://{host}/wday/cxs/{tenant}/{site}/jobs",
                enabled=False,
                poll_interval_minutes=180,
                config=config,
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        else:
            source.adapter = ADAPTER_PATH
            source.base_url = "https://{host}/wday/cxs/{tenant}/{site}/jobs"
            merged = dict(source.config or {})
            for key, value in config.items():
                merged.setdefault(key, value)
            source.config = merged
            session.commit()

        seed_tenants(session, source=source, seeds=DEFAULT_TENANTS)
        return source.id


def load_sites(source_id: int) -> list[WorkdaySite]:
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("Workday source disappeared before tenant loading")
        tenants = enabled_tenants(session, source=source)
        sites: list[WorkdaySite] = []
        for row in tenants:
            seed = TenantSeed(
                tenant_key=row.tenant_key,
                company=row.company,
                config=dict(row.config or {}),
                enabled=row.enabled,
            )
            sites.append(_site_from_seed(seed))
        if not sites:
            raise RuntimeError("No enabled Workday tenants are registered")
        return sites


async def _preflight(delay: float) -> int:
    localities = _localities()
    failures = 0
    for seed in DEFAULT_TENANTS:
        site = _site_from_seed(seed)
        adapter = WorkdayJobSource(
            sites=[site],
            austrian_localities=localities,
            request_delay_seconds=delay,
        )
        unique: dict[str, object] = {}
        print()
        print(f"===== WORKDAY {site.tenant}/{site.site} =====")
        for shard in adapter.default_shards():
            search_text = shard.params.get("search_text")
            try:
                batch = await adapter.fetch_shard(shard)
            except Exception as exc:
                failures += 1
                print(
                    f"query={search_text!r} status=failed "
                    f"error={type(exc).__name__}: {exc}"
                )
                continue
            print(
                f"query={search_text!r} status=ok "
                f"reported={batch.source_reported_count} "
                f"austrian={len(batch.items)} pages={batch.pages_fetched} "
                f"cap={batch.result_cap_hit}"
            )
            for job in batch.items:
                unique[job.source_listing_id] = job

        accepted = []
        rejected = []
        for job in unique.values():
            decision = classify_job_candidate(job)
            row = (job, decision)
            (accepted if decision.accepted else rejected).append(row)

        print(
            f"site_summary unique_austrian={len(unique)} "
            f"accepted={len(accepted)} rejected={len(rejected)}"
        )
        for job, decision in accepted:
            print(
                f"  ACCEPT title={job.title!r} "
                f"locations={[row.location_text for row in job.locations]!r} "
                f"reason={decision.reason} url={job.url}"
            )
        for job, decision in rejected[:20]:
            print(f"  reject title={job.title!r} reason={decision.reason}")
        if len(rejected) > 20:
            print(f"  ... {len(rejected) - 20} more rejected")

    print()
    print(f"workday_preflight_failures={failures}")
    return 0 if failures == 0 else 1


async def async_main() -> int:
    args = parse_args()
    if args.preflight:
        return await _preflight(args.delay)

    source_id = get_or_create_source()
    if args.seed:
        print(f"workday_source_id={source_id}")
        print("workday_seed=success")
        return 0

    adapter = WorkdayJobSource(
        sites=load_sites(source_id),
        austrian_localities=_localities(),
        request_delay_seconds=args.delay,
    )
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("Workday source disappeared before the run started")
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
            f"failed={summary.shards_failed} pages={summary.pages_fetched}"
        )
        print(
            f"seen={summary.items_seen} new={summary.items_new} "
            f"updated={summary.items_updated} source_reported={summary.source_reported_count}"
        )
    return 0 if summary.run_status != "failed" else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
