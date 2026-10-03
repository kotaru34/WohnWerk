from __future__ import annotations

import asyncio

from app.sources.base import SourceFetchError
from app.sources.property.iad_de import IadGermanyPropertySource
from app.sources.property.remax_de import RemaxGermanyPropertySource


def _assert_frontier(label: str, batch) -> None:
    cards_seen = int(batch.next_cursor.get("frontier_cards_seen") or 0)
    cards_parsed = int(batch.next_cursor.get("frontier_cards_parsed") or 0)
    if cards_seen <= 0:
        raise RuntimeError(f"{label}: live page exposed no identifiable cards")
    if cards_seen != cards_parsed:
        raise RuntimeError(
            f"{label}: live parser incomplete: parsed {cards_parsed}/{cards_seen}"
        )
    if batch.coverage_complete:
        raise RuntimeError(f"{label}: bounded frontier unexpectedly claimed full coverage")
    print(
        f"{label}: cards={cards_seen} parsed={cards_parsed} "
        f"items_in_budget={len(batch.items)} source_reported={batch.source_reported_count} "
        f"pages={batch.pages_fetched} coverage_complete={batch.coverage_complete}"
    )
    for item in batch.items[:3]:
        print(
            f"  id={item.source_listing_id} plz={item.postal_code} city={item.city!r} "
            f"price={item.price_eur} living={item.living_area_m2} plot={item.plot_area_m2}"
        )


async def _probe_remax() -> None:
    source = RemaxGermanyPropertySource(request_delay_seconds=2.0)
    shard = next(shard for shard in source.default_shards() if shard.key == "saarland")
    try:
        batch = await source.fetch_shard(shard, reconciliation=False)
    except SourceFetchError as exc:
        if exc.halt_source and "challenge" in str(exc).casefold():
            print("remax-de: access=challenge fail_closed=yes scheduled=no")
            return
        raise
    _assert_frontier("remax-de", batch)
    print("remax-de: access=ok scheduled=no diagnostic_only=yes")


async def _probe_iad() -> None:
    source = IadGermanyPropertySource(
        request_delay_seconds=2.0,
        frontier_pages=1,
        hard_max_pages=40,
    )
    batch = await source.fetch_shard(source.default_shards()[0], reconciliation=False)
    _assert_frontier("iad-de", batch)
    print("iad-de: access=ok scheduled=yes")


async def async_main() -> int:
    await _probe_remax()
    await _probe_iad()
    print("live_probe=ok")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
