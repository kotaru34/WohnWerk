from __future__ import annotations

import asyncio

from app.sources.property.falc_de import FalcGermanyPropertySource


async def async_main() -> int:
    source = FalcGermanyPropertySource(
        request_delay_seconds=2.0,
        frontier_pages=1,
        hard_max_pages=40,
    )
    batch = await source.fetch_shard(source.default_shards()[0], reconciliation=False)
    cursor = batch.next_cursor
    cards_seen = int(cursor.get("frontier_cards_seen") or 0)
    cards_parsed = int(cursor.get("frontier_cards_parsed") or 0)
    identity_failures = int(cursor.get("detail_identity_failures") or 0)

    if cards_seen <= 0:
        raise RuntimeError("FALC live page exposed no identifiable house cards")
    if cards_seen != cards_parsed:
        raise RuntimeError(
            f"FALC live parser incomplete: parsed {cards_parsed}/{cards_seen}"
        )
    if identity_failures:
        raise RuntimeError(
            f"FALC stable identity failed for {identity_failures} in-budget cards"
        )
    if batch.coverage_complete:
        raise RuntimeError("FALC bounded frontier unexpectedly claimed full coverage")

    print(
        f"cards={cards_seen} parsed={cards_parsed} "
        f"items_in_budget={len(batch.items)} "
        f"source_reported={batch.source_reported_count} "
        f"pages={batch.pages_fetched} coverage_complete={batch.coverage_complete}"
    )
    for item in batch.items[:5]:
        print(
            f"id={item.source_listing_id} plz={item.postal_code} city={item.city!r} "
            f"price={item.price_eur} living={item.living_area_m2} plot={item.plot_area_m2} "
            f"heating={item.raw_payload.get('heating_types', [])}"
        )
    print("falc_live_probe=ok")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
