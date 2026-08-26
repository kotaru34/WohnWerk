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

            print(f"{source.name} [{source.category}] coverage={source.coverage_status}")
            print(
                f"  shards={shard_total} unhealthy_shards={shard_failures} "
                f"incremental={_age(source.last_incremental_at)} "
                f"reconcile={_age(source.last_reconciliation_at)}"
            )

            if latest_run is None:
                print("  latest_run=never")
                continue

            incomplete = session.scalar(
                select(func.count()).select_from(CrawlShardRun).where(
                    CrawlShardRun.crawl_run_id == latest_run.id,
                    CrawlShardRun.status != RunStatus.SUCCESS,
                )
            ) or 0
            cap_hits = session.scalar(
                select(func.count()).select_from(CrawlShardRun).where(
                    CrawlShardRun.crawl_run_id == latest_run.id,
                    CrawlShardRun.result_cap_hit.is_(True),
                )
            ) or 0
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

            failures = list(
                session.execute(
                    select(SourceShard.key, CrawlShardRun.error)
                    .join(CrawlShardRun, CrawlShardRun.shard_id == SourceShard.id)
                    .where(
                        CrawlShardRun.crawl_run_id == latest_run.id,
                        CrawlShardRun.status == RunStatus.FAILED,
                    )
                    .order_by(SourceShard.key)
                    .limit(5)
                )
            )
            for shard_key, error in failures:
                compact = " ".join((error or "unknown error").split())
                if len(compact) > 220:
                    compact = compact[:217] + "..."
                print(f"  error[{shard_key}]={compact}")
            if incomplete > len(failures):
                print(f"  ... {incomplete - len(failures)} more incomplete shard(s)")


if __name__ == "__main__":
    main()
