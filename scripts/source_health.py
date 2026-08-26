from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import CrawlRun, CrawlShardRun, RunStatus, Source, SourceShard


def _age(value: datetime | None) -> str:
    if value is None:
        return "never"
    now = datetime.now(UTC)
    seconds = max(0, int((now - value).total_seconds()))
    if seconds < 120:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 120:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def main() -> None:
    with SessionLocal() as session:
        sources = list(session.scalars(select(Source).order_by(Source.category, Source.name)))
        if not sources:
            print("No acquisition sources configured yet.")
            return

        for source in sources:
            shard_total = session.scalar(
                select(func.count()).select_from(SourceShard).where(
                    SourceShard.source_id == source.id,
                    SourceShard.enabled.is_(True),
                )
            ) or 0
            shard_failures = session.scalar(
                select(func.count()).select_from(SourceShard).where(
                    SourceShard.source_id == source.id,
                    SourceShard.enabled.is_(True),
                    SourceShard.consecutive_failures > 0,
                )
            ) or 0
            latest_run = session.scalar(
                select(CrawlRun)
                .where(CrawlRun.source_id == source.id)
                .order_by(CrawlRun.started_at.desc())
                .limit(1)
            )

            state = "enabled" if source.enabled else "disabled"
            print(
                f"{source.name} [{source.category}] {state} coverage={source.coverage_status}"
            )
            print(
                f"  shards={shard_total} unhealthy_shards={shard_failures} "
                f"incremental={_age(source.last_incremental_at)} "
                f"reconcile={_age(source.last_reconciliation_at)}"
            )

            if latest_run is None:
                print("  latest_run=never")
                continue

            shard_rows = list(
                session.execute(
                    select(SourceShard.key, CrawlShardRun)
                    .join(CrawlShardRun, CrawlShardRun.shard_id == SourceShard.id)
                    .where(CrawlShardRun.crawl_run_id == latest_run.id)
                    .order_by(SourceShard.key)
                )
            )
            incomplete = sum(row.status != RunStatus.SUCCESS for _, row in shard_rows)
            cap_hits = sum(row.result_cap_hit for _, row in shard_rows)

            print(
                f"  latest_run={latest_run.id} mode={latest_run.mode} status={latest_run.status} "
                f"coverage={latest_run.coverage_status} seen={latest_run.items_seen} "
                f"new={latest_run.items_new} updated={latest_run.items_updated} "
                f"disappeared={latest_run.items_disappeared}"
            )
            print(
                f"  pages={latest_run.pages_fetched} shards={latest_run.shards_completed}/"
                f"{latest_run.shards_total} incomplete={incomplete} cap_hits={cap_hits}"
            )

            failures = [(key, row.error) for key, row in shard_rows if row.status == RunStatus.FAILED]
            for shard_key, error in failures[:5]:
                compact = " ".join((error or "unknown error").split())
                if len(compact) > 220:
                    compact = compact[:217] + "..."
                print(f"  error[{shard_key}]={compact}")
            if len(failures) > 5:
                print(f"  ... {len(failures) - 5} more incomplete shard(s)")

            if source.enabled:
                for shard_key, row in shard_rows:
                    cursor = row.next_cursor or {}
                    cards = cursor.get("discovery_cards_seen")
                    parsed = cursor.get("discovery_cards_parsed")
                    synthetic = cursor.get("discovery_synthetic_cards")
                    synthetic_tolerance = cursor.get("discovery_synthetic_tolerance")
                    link_quality = cursor.get("discovery_link_quality_ok")
                    latest_reported = cursor.get("discovery_latest_reported")
                    max_reported = cursor.get("discovery_max_reported")
                    target_pages = cursor.get("discovery_target_pages")
                    traversal = cursor.get("discovery_traversal_complete")
                    failed_page = cursor.get("discovery_failed_page")
                    failed_cards = cursor.get("discovery_failed_page_cards_seen")
                    failed_parsed = cursor.get("discovery_failed_page_cards_parsed")
                    max_page = cursor.get("discovery_observed_max_page")
                    terminal = cursor.get("discovery_terminal_reached")
                    count_delta = cursor.get("discovery_count_delta")
                    count_tolerance = cursor.get("discovery_count_tolerance")

                    coverage_bits = ""
                    if cards is not None:
                        coverage_bits += f" cards={cards}"
                    if parsed is not None:
                        coverage_bits += f" parsed={parsed}"
                    if synthetic is not None:
                        coverage_bits += f" synthetic={synthetic}"
                    if synthetic_tolerance is not None:
                        coverage_bits += f" synthetic_tol={synthetic_tolerance}"
                    if link_quality is not None:
                        coverage_bits += f" link_quality={'ok' if link_quality else 'warn'}"
                    if latest_reported is not None:
                        coverage_bits += f" latest_reported={latest_reported}"
                    if max_reported is not None:
                        coverage_bits += f" max_reported={max_reported}"
                    if target_pages is not None:
                        coverage_bits += f" target_pages={target_pages}"
                    if traversal is not None:
                        coverage_bits += f" traversal={'yes' if traversal else 'no'}"
                    if failed_page is not None:
                        coverage_bits += f" failed_page={failed_page}"
                    if failed_cards is not None or failed_parsed is not None:
                        coverage_bits += f" failed_cards={failed_parsed}/{failed_cards}"
                    if max_page is not None:
                        coverage_bits += f" max_page={max_page}"
                    if terminal is not None:
                        coverage_bits += f" terminal={'yes' if terminal else 'no'}"
                    if count_delta is not None:
                        coverage_bits += f" delta={count_delta}"
                    if count_tolerance is not None:
                        coverage_bits += f" tolerance={count_tolerance}"

                    print(
                        f"  shard[{shard_key}] status={row.status} pages={row.pages_fetched} "
                        f"seen={row.items_seen}{coverage_bits} reported={row.source_reported_count} "
                        f"complete={'yes' if row.coverage_complete else 'no'} "
                        f"cap={'yes' if row.result_cap_hit else 'no'}"
                    )


if __name__ == "__main__":
    main()
