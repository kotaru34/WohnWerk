from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.property_runner import run_property_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.property.kleinanzeigen_de import (
    BASE_URL,
    KleinanzeigenGermanyPropertySource,
)

SOURCE_NAME = "kleinanzeigen-de"
ADAPTER_PATH = "app.sources.property.kleinanzeigen_de.KleinanzeigenGermanyPropertySource"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the bounded newest-first Kleinanzeigen German house frontier."
    )
    parser.add_argument("--frontier-pages", type=int, default=12)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--hard-max-pages", type=int, default=40)
    parser.add_argument(
        "--detail-checks-per-shard", type=int, default=None,
        help=(
            "Optional diagnostic cap for detail GETs per shard. "
            "Default: enrich every discovered in-budget house."
        ),
    )
    parser.add_argument(
        "--enable-regional-expansion",
        action="store_true",
        help=(
            "Persistently enable four regional frontiers alongside the existing "
            "nationwide shard (24 pages total per scan); explicit operator action"
        ),
    )
    parser.add_argument(
        "--activate-regional-expansion-only",
        action="store_true",
        help="Persistently enable hybrid discovery; do not run a crawl immediately",
    )
    return parser.parse_args()


def get_or_create_source(*, enable_regional_expansion: bool = False) -> int:
    config = {
        "country_code": "DE",
        "scope": (
            "Kleinanzeigen public newest-first house offers; local WohnWerk budget "
            "EUR 30,000..200,000"
        ),
        "acquisition": (
            "bounded public search frontier plus per-result typed detail enrichment; "
            "no login, messages or seller contact extraction"
        ),
        "retention": (
            "source ID/URL, title, price, visible living area, PLZ/city and bounded "
            "source-backed heating facts; no descriptions, contacts or photos"
        ),
        "coverage": (
            "frontier-only and never authoritative for disappearance; old listings remain "
            "active until checked by another source/liveness path"
        ),
        "rate_policy": "low-rate HTTP with >=2 second jittered spacing and 429/5xx backoff",
    }
    if enable_regional_expansion:
        config["regional_expansion_enabled"] = True
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        if source is None:
            source = Source(
                name=SOURCE_NAME,
                category=SourceCategory.PROPERTY,
                adapter=ADAPTER_PATH,
                base_url=BASE_URL,
                enabled=True,
                poll_interval_minutes=90,
                config=config,
            )
            session.add(source)
            session.commit()
            session.refresh(source)
        else:
            source.adapter = ADAPTER_PATH
            source.base_url = BASE_URL
            source.enabled = True
            source.config = {**(source.config or {}), **config}
            session.commit()
        return source.id


async def async_main() -> int:
    args = parse_args()
    if args.frontier_pages <= 0 or args.hard_max_pages <= 0:
        raise SystemExit("--frontier-pages and --hard-max-pages must be positive")
    detail_checks = getattr(args, "detail_checks_per_shard", None)
    if detail_checks is not None and detail_checks < 0:
        raise SystemExit("--detail-checks-per-shard must be non-negative")

    source_id = get_or_create_source(
        enable_regional_expansion=(
            args.enable_regional_expansion or args.activate_regional_expansion_only
        )
    )
    if args.activate_regional_expansion_only:
        # Persist the feature flag only. The normal refresh timer will pick up the
        # added shards on the next scheduled run. This path makes NO HTTP request.
        print(f"Regional expansion activated for source #{source_id}; no crawl started")
        return 0
    with SessionLocal() as session:
        source = session.get(Source, source_id)
        if source is None:
            raise RuntimeError("Kleinanzeigen source disappeared before the run started")
        regional_expansion = bool(
            (source.config or {}).get("regional_expansion_enabled", False)
        )
        adapter = KleinanzeigenGermanyPropertySource(
            request_delay_seconds=max(2.0, args.delay),
            frontier_pages=args.frontier_pages,
            hard_max_pages=args.hard_max_pages,
            regional_expansion=regional_expansion,
            detail_checks_per_shard=detail_checks,
        )
        run, summary = await run_property_source(
            session,
            source=source,
            adapter=adapter,
            reconciliation=False,
        )
        print(f"Run #{run.id}: {run.mode}")
        print(f"status={summary.run_status} coverage={summary.coverage_status}")
        print(
            f"pages={summary.pages_fetched} seen={summary.items_seen} "
            f"new={summary.items_new} updated={summary.items_updated} "
            f"source_reported={summary.source_reported_count}"
        )
        print("disappearance_authority=never frontier_only=yes")
        return 0 if summary.run_status != "failed" else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
