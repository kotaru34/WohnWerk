from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.crawling.property_runner import run_property_source
from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.sources.property.immmo import BASE_URL
from app.sources.property.immmo_v3 import ImmmoPropertySource

ADAPTER_PATH = "app.sources.property.immmo_v3.ImmmoPropertySource"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Austrian IMMMO house-for-sale meta-search discovery source."
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Scan every Bundesland shard completely and reconcile only on OK coverage.",
    )
    parser.add_argument(
        "--incremental-pages",
        type=int,
        default=2,
        help="Newest pages per Bundesland for a normal incremental run (default: 2).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.45,
        help="Base delay between HTTP requests, with jitter (default: 0.45 seconds).",
    )
    parser.add_argument(
        "--hard-max-pages-per-shard",
        type=int,
        default=500,
        help="Safety ceiling for one Bundesland reconciliation (default: 500 pages).",
    )
    return parser.parse_args()


def get_or_create_source() -> Source:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == "immmo.at"))
        if source is None:
            source = Source(
                name="immmo.at",
                category=SourceCategory.PROPERTY,
                adapter=ADAPTER_PATH,
                base_url=BASE_URL,
                enabled=True,
                poll_interval_minutes=30,
                config={
                    "scope": "Austria houses for sale",
                    "acquisition": "public meta-search result pages; minimal metadata retention",
                    "sharding": "Bundesland",
                    "incremental_pages": 2,
                    "reconciliation_interval_hours": 24,
                },
            )
            session.add(source)
        else:
            source.adapter = ADAPTER_PATH
            source.enabled = True
        session.commit()
        session.refresh(source)
        return source


async def async_main() -> int:
    args = parse_args()
    source = get_or_create_source()
    adapter = ImmmoPropertySource(
        request_delay_seconds=args.delay,
        incremental_pages=args.incremental_pages,
        hard_max_pages_per_shard=args.hard_max_pages_per_shard,
    )

    with SessionLocal() as session:
        source = session.get(Source, source.id)
        if source is None:
            raise RuntimeError("IMMMO source disappeared before the run started")
        run, summary = await run_property_source(
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
            continuity = (run.run_metadata or {}).get("immmo_continuity")
            if isinstance(continuity, dict):
                strategies = continuity.get("strategies") or {}
                strategy_label = (
                    ",".join(
                        f"{key}:{value}" for key, value in sorted(strategies.items())
                    )
                    if isinstance(strategies, dict)
                    else "-"
                )
                print(
                    "continuity_merged="
                    f"{continuity.get('matched', 0)} "
                    "new_rows_reclassified="
                    f"{continuity.get('new_rows_reclassified', 0)} "
                    f"strategies={strategy_label or '-'}"
                )
            print(f"disappeared={run.items_disappeared}")

    return 0 if summary.run_status != "failed" else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
