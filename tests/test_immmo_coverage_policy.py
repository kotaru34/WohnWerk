from app.sources.base import SourceBatch
from app.sources.property.thumbnail_capture import _reassess_immmo_coverage


def _batch(*, synthetic: int) -> SourceBatch:
    return SourceBatch(
        items=[],
        next_cursor={
            "discovery_cards_seen": 1805,
            "discovery_cards_parsed": 1805,
            "discovery_synthetic_cards": synthetic,
            "discovery_count_delta": 0,
            "discovery_count_tolerance": 24,
            "discovery_traversal_complete": True,
        },
        source_reported_count=1805,
        coverage_complete=False,
        result_cap_hit=False,
        pages_fetched=151,
    )


def test_stable_oberoesterreich_synthetic_share_is_complete() -> None:
    batch = _batch(synthetic=103)

    _reassess_immmo_coverage(batch, reconciliation=True)

    assert batch.coverage_complete is True
    assert batch.next_cursor["discovery_synthetic_tolerance"] == 145
    assert batch.next_cursor["discovery_link_quality_ok"] is True


def test_large_synthetic_spike_still_degrades_coverage() -> None:
    batch = _batch(synthetic=200)

    _reassess_immmo_coverage(batch, reconciliation=True)

    assert batch.coverage_complete is False
    assert batch.next_cursor["discovery_link_quality_ok"] is False
