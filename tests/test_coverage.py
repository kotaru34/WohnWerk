from app.crawling.coverage import ShardOutcome, summarize_shards
from app.models import CoverageStatus, RunStatus


def test_complete_shards_produce_ok_coverage() -> None:
    summary = summarize_shards(
        [
            ShardOutcome(
                status=RunStatus.SUCCESS,
                pages_fetched=4,
                items_seen=80,
                items_new=5,
                coverage_complete=True,
            ),
            ShardOutcome(
                status=RunStatus.SUCCESS,
                pages_fetched=3,
                items_seen=60,
                items_updated=2,
                coverage_complete=True,
            ),
        ]
    )

    assert summary.run_status == RunStatus.SUCCESS
    assert summary.coverage_status == CoverageStatus.OK
    assert summary.shards_completed == 2
    assert summary.pages_fetched == 7
    assert summary.items_seen == 140


def test_successful_frontier_scan_is_success_with_degraded_coverage() -> None:
    summary = summarize_shards(
        [
            ShardOutcome(
                status=RunStatus.SUCCESS,
                pages_fetched=1,
                items_seen=14,
                coverage_complete=False,
            )
        ]
    )

    assert summary.run_status == RunStatus.SUCCESS
    assert summary.coverage_status == CoverageStatus.DEGRADED
    assert summary.shards_completed == 1
    assert summary.shards_failed == 0


def test_cap_hit_degrades_coverage_without_turning_execution_partial() -> None:
    summary = summarize_shards(
        [
            ShardOutcome(
                status=RunStatus.SUCCESS,
                items_seen=1000,
                result_cap_hit=True,
                coverage_complete=False,
            )
        ]
    )

    assert summary.run_status == RunStatus.SUCCESS
    assert summary.coverage_status == CoverageStatus.DEGRADED


def test_one_failed_shard_prevents_complete_reconciliation() -> None:
    summary = summarize_shards(
        [
            ShardOutcome(status=RunStatus.SUCCESS, coverage_complete=True),
            ShardOutcome(status=RunStatus.FAILED, coverage_complete=False),
        ]
    )

    assert summary.run_status == RunStatus.PARTIAL
    assert summary.coverage_status == CoverageStatus.DEGRADED
    assert summary.shards_failed == 1


def test_empty_source_is_failure_not_false_success() -> None:
    summary = summarize_shards([])

    assert summary.run_status == RunStatus.FAILED
    assert summary.coverage_status == CoverageStatus.FAILED
