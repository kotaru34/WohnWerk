from __future__ import annotations

import argparse
import asyncio
import os
import shlex
from pathlib import Path

from sqlalchemy import select

from app.crawling.challenge import ExternalCommandChallengeHandler
from app.crawling.coverage import RUN_STATUS_PAUSED
from app.crawling.property_runner import run_property_source
from app.database import SessionLocal
from app.models import CrawlMode, CrawlRun, Source, SourceCategory
from app.sources.property.immowelt_de import BASE_URL
from app.sources.property.immowelt_de_headed import ImmoweltHeadedPropertySource

SOURCE_NAME = "immowelt-de"
ADAPTER_PATH = "app.sources.property.immowelt_de_headed.ImmoweltHeadedPropertySource"
DEFAULT_CHALLENGE_STATE_ROOT = Path("/var/lib/wohnwerk/challenge-state")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the public German Immowelt house-for-sale source."
    )
    parser.add_argument("--reconcile", action="store_true")
    parser.add_argument("--incremental-pages", type=int, default=2)
    parser.add_argument("--delay", type=float, default=15.0)
    parser.add_argument("--hard-max-pages", type=int, default=250)
    parser.add_argument(
        "--challenge-handler",
        default=os.environ.get("WOHNWERK_IMMOWELT_CHALLENGE_HANDLER"),
        help=(
            "User-provided external handler command. Receives one JSON request on stdin and "
            "must return JSON with action=resolved|defer|abort on stdout."
        ),
    )
    parser.add_argument(
        "--challenge-handler-timeout",
        type=float,
        default=900.0,
        help="Maximum seconds to wait for the user-provided handler (default: 900).",
    )
    parser.add_argument(
        "--challenge-state-root",
        type=Path,
        default=DEFAULT_CHALLENGE_STATE_ROOT,
        help=f"Persisted browser handoff root (default: {DEFAULT_CHALLENGE_STATE_ROOT}).",
    )
    return parser.parse_args()


def get_or_create_source() -> int:
    config = {
        "country_code": "DE",
        "scope": "Germany houses for sale priced EUR 30,000 through EUR 300,000",
        "acquisition": (
            "public browser-rendered search pages; no detail pages or login; explicit challenge "
            "detection with state handoff to an operator-provided external interface"
        ),
        "retention": "title, price, area, PLZ, city and source URL only; no contact data or photos",
        "sharding": "16 states/city-states x 3 non-overlapping price bands",
        "ordering": (
            "newest first; incremental shard scheduling is least-recently-successful first; "
            "the exact shard order is frozen inside a resumable crawl run"
        ),
        "coverage": (
            "authoritative only when every shard is exhaustively parsed below page 250; "
            "paused, skipped, failed or otherwise degraded runs have no disappearance authority"
        ),
        "rate_policy": (
            "low-rate navigation with roughly 15-second jittered spacing; 429 backs off; "
            "explicit challenges checkpoint the exact page before external handoff"
        ),
        "runtime": "headed Playwright Chromium on an Xvfb display is required",
        "challenge_handler_contract": (
            "external executable only; JSON stdin request and JSON stdout disposition; "
            "WohnWerk contains no challenge-solving implementation"
        ),
        "reconciliation_interval_hours": 24,
    }
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == SOURCE_NAME))
        if source is None:
            source = Source(
                name=SOURCE_NAME,
                category=SourceCategory.PROPERTY,
                adapter=ADAPTER_PATH,
                base_url=BASE_URL,
                enabled=True,
                poll_interval_minutes=180,
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


def _latest_paused_run(source_id: int) -> CrawlRun | None:
    with SessionLocal() as session:
        return session.scalar(
            select(CrawlRun)
            .where(
                CrawlRun.source_id == source_id,
                CrawlRun.status == RUN_STATUS_PAUSED,
                CrawlRun.finished_at.is_(None),
            )
            .order_by(CrawlRun.started_at.desc(), CrawlRun.id.desc())
            .limit(1)
        )


def _challenge_handler(args: argparse.Namespace) -> ExternalCommandChallengeHandler | None:
    raw = str(args.challenge_handler or "").strip()
    if not raw:
        return None
    command = shlex.split(raw)
    if not command:
        return None
    return ExternalCommandChallengeHandler(
        command,
        timeout_seconds=max(1.0, args.challenge_handler_timeout),
    )


async def async_main() -> int:
    args = parse_args()
    if args.incremental_pages <= 0 or args.hard_max_pages <= 0:
        raise SystemExit("--incremental-pages and --hard-max-pages must be positive")

    source_id = get_or_create_source()
    paused = _latest_paused_run(source_id)
    reconciliation = args.reconcile
    resume_run_id: int | None = None
    if paused is not None:
        resume_run_id = paused.id
        reconciliation = paused.mode == CrawlMode.RECONCILIATION
        print(f"resuming_run={paused.id} mode={paused.mode}")

    adapter = ImmoweltHeadedPropertySource(
        request_delay_seconds=max(1.0, args.delay),
        incremental_pages=args.incremental_pages,
        hard_max_pages=args.hard_max_pages,
    )
    try:
        with SessionLocal() as session:
            source = session.get(Source, source_id)
            if source is None:
                raise RuntimeError("Immowelt DE source disappeared before the run started")
            run, summary = await run_property_source(
                session,
                source=source,
                adapter=adapter,
                reconciliation=reconciliation,
                challenge_handler=_challenge_handler(args),
                challenge_state_root=args.challenge_state_root,
                resume_run_id=resume_run_id,
            )

            print(f"Run #{run.id}: {run.mode}")
            print(f"status={summary.run_status} coverage={summary.coverage_status}")
            print(
                "shards="
                f"{summary.shards_completed}/{summary.shards_total} "
                f"failed={summary.shards_failed} skipped={summary.shards_skipped} "
                f"paused={summary.shards_paused} pages={summary.pages_fetched}"
            )
            print(
                f"seen={summary.items_seen} new={summary.items_new} "
                f"updated={summary.items_updated} source_reported={summary.source_reported_count}"
            )
            if reconciliation and summary.coverage_status == "ok":
                print(f"disappeared={run.items_disappeared}")
            elif reconciliation:
                print("disappeared=0 authority=withheld")
        return 0 if summary.run_status != "failed" else 1
    finally:
        await adapter.aclose()


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
