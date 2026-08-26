from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models import CrawlRun, CrawlShardRun, Source, SourceShard


def main() -> None:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == "sreal.at"))
        if source is None:
            print("sreal.at source not configured")
            return
        run = session.scalar(
            select(CrawlRun)
            .where(CrawlRun.source_id == source.id)
            .order_by(CrawlRun.started_at.desc())
            .limit(1)
        )
        if run is None:
            print("sreal.at has no crawl runs")
            return

        rows = list(
            session.execute(
                select(SourceShard.key, CrawlShardRun)
                .join(CrawlShardRun, CrawlShardRun.shard_id == SourceShard.id)
                .where(CrawlShardRun.crawl_run_id == run.id)
                .order_by(SourceShard.key)
            )
        )
        print(
            f"run={run.id} mode={run.mode} status={run.status} "
            f"coverage={run.coverage_status} seen={run.items_seen}"
        )
        for key, shard_run in rows:
            cursor = shard_run.next_cursor or {}
            raw_anchors = cursor.get("discovery_raw_detail_anchors")
            duplicate_anchors = cursor.get("discovery_duplicate_detail_anchors")
            metadata_fallbacks = cursor.get("discovery_metadata_fallbacks")
            extras = ""
            if raw_anchors is not None:
                extras += f" raw_anchors={raw_anchors}"
            if duplicate_anchors is not None:
                extras += f" duplicate_anchors={duplicate_anchors}"
            if metadata_fallbacks is not None:
                extras += f" metadata_fallbacks={metadata_fallbacks}"
            print(
                f"  shard[{key}] pages={shard_run.pages_fetched} "
                f"cards={cursor.get('discovery_cards_seen')} "
                f"parsed={cursor.get('discovery_cards_parsed')} "
                f"max_page={cursor.get('discovery_max_page')}"
                f"{extras} "
                f"detail={cursor.get('detail_enrichment_succeeded', 0)}/"
                f"{cursor.get('detail_enrichment_attempted', 0)} "
                f"detail_failed={cursor.get('detail_enrichment_failed', 0)}"
            )


if __name__ == "__main__":
    main()
