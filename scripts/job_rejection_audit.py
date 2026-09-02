from __future__ import annotations

import argparse

from sqlalchemy import select

from app.database import SessionLocal
from app.models import CrawlRun, CrawlShardRun, Source, SourceShard


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show bounded rejected-job audit samples from a crawl run."
    )
    parser.add_argument("source", help="Job source name")
    parser.add_argument("--run-id", type=int, help="Specific crawl run; defaults to latest")
    parser.add_argument("--tenant", help="Optional shard/tenant key filter")
    return parser.parse_args()


def _matches(sample: dict, key: str) -> str:
    value = sample.get(key)
    if not isinstance(value, list) or not value:
        return "-"
    return ",".join(str(item) for item in value)


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == args.source))
        if source is None:
            raise SystemExit(f"Unknown source: {args.source}")

        if args.run_id is not None:
            run = session.scalar(
                select(CrawlRun).where(
                    CrawlRun.id == args.run_id,
                    CrawlRun.source_id == source.id,
                )
            )
        else:
            run = session.scalar(
                select(CrawlRun)
                .where(CrawlRun.source_id == source.id)
                .order_by(CrawlRun.started_at.desc())
                .limit(1)
            )
        if run is None:
            raise SystemExit(f"No matching crawl run for source: {args.source}")

        rows = list(
            session.execute(
                select(SourceShard.key, CrawlShardRun)
                .join(CrawlShardRun, CrawlShardRun.shard_id == SourceShard.id)
                .where(CrawlShardRun.crawl_run_id == run.id)
                .order_by(SourceShard.key)
            )
        )

        print(f"source={source.name} run={run.id} mode={run.mode} status={run.status}")
        for shard_key, shard_run in rows:
            if args.tenant and shard_key != args.tenant:
                continue
            cursor = shard_run.next_cursor or {}
            rejected = cursor.get("job_candidates_rejected") or 0
            sample = cursor.get("job_rejected_audit_sample") or []
            if not isinstance(sample, list):
                sample = []
            print(f"[{shard_key}] rejected={rejected} audit_sample={len(sample)}")
            for item in sample:
                if not isinstance(item, dict):
                    continue
                print(f"  - {item.get('title') or '<untitled>'}")
                print(
                    "    "
                    f"reason={item.get('reason') or '-'} "
                    f"strong={_matches(item, 'strong_title_matches')} "
                    f"adjacent={_matches(item, 'adjacent_title_matches')}"
                )
                print(
                    "    "
                    f"domains={_matches(item, 'domain_matches')} "
                    f"methods={_matches(item, 'method_tool_matches')} "
                    f"negative={_matches(item, 'negative_context_matches')} "
                    f"low={_matches(item, 'low_relevance_title_matches')}"
                )


if __name__ == "__main__":
    main()
