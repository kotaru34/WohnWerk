from app.crawling.immmo_quality import (
    COVERAGE_POLICY_VERSION,
    annotate_immmo_coverage_cursor,
    decide_immmo_coverage,
)
from app.sources.base import RawProperty, SourceBatch


def _batch(*, cards: int, cap: bool = False, traversal: bool = True) -> SourceBatch[RawProperty]:
    return SourceBatch(
        items=[],
        next_cursor={
            "discovery_cards_seen": cards,
            "discovery_cards_parsed": cards,
            "discovery_count_delta": 0,
            "discovery_count_tolerance": max(24, cards // 100),
            "discovery_traversal_complete": traversal,
            # Legacy metric may be false for a healthy source when IMMMO intentionally
            # omits downstream URLs from many cards. It must not decide authority.
            "discovery_link_quality_ok": False,
        },
        source_reported_count=cards,
        coverage_complete=False,
        result_cap_hit=cap,
        pages_fetched=1,
    )


def test_stable_source_less_inventory_can_still_be_authoritative() -> None:
    decision = decide_immmo_coverage(
        _batch(cards=1053),
        reconciliation=True,
        synthetic_new=3,
    )

    assert decision.structural_complete is True
    assert decision.synthetic_new_tolerance == 11
    assert decision.identity_churn_ok is True
    assert decision.coverage_complete is True


def test_large_new_synthetic_identity_spike_fails_closed() -> None:
    decision = decide_immmo_coverage(
        _batch(cards=1053),
        reconciliation=True,
        synthetic_new=91,
    )

    assert decision.structural_complete is True
    assert decision.synthetic_new_tolerance == 11
    assert decision.identity_churn_ok is False
    assert decision.coverage_complete is False


def test_structural_failure_remains_non_authoritative() -> None:
    decision = decide_immmo_coverage(
        _batch(cards=1000, traversal=False),
        reconciliation=True,
        synthetic_new=0,
    )

    assert decision.structural_complete is False
    assert decision.identity_churn_ok is True
    assert decision.coverage_complete is False


def test_incremental_run_never_claims_complete_coverage() -> None:
    decision = decide_immmo_coverage(
        _batch(cards=24),
        reconciliation=False,
        synthetic_new=0,
    )

    assert decision.structural_complete is False
    assert decision.coverage_complete is False


def test_cursor_keeps_legacy_link_metric_as_diagnostic_only() -> None:
    decision = decide_immmo_coverage(
        _batch(cards=431),
        reconciliation=True,
        synthetic_new=2,
    )

    cursor = annotate_immmo_coverage_cursor(
        {"discovery_link_quality_ok": False},
        decision,
    )

    assert cursor["discovery_coverage_policy"] == COVERAGE_POLICY_VERSION
    assert cursor["discovery_structural_coverage_ok"] is True
    assert cursor["discovery_synthetic_new"] == 2
    assert cursor["discovery_synthetic_new_tolerance"] == 5
    assert cursor["discovery_identity_churn_ok"] is True
    assert cursor["discovery_legacy_link_quality_ok"] is False
