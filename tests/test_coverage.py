from app.crawling.coverage import (
    RUN_STATUS_PAUSED,
    SHARD_STATUS_SKIPPED,
    ShardOutcome,
    create_run,
    summarize_shards,
)
from app.models import CoverageStatus, CrawlMode, RunStatus


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


def test_source_halt_counts_actual_failure_separately_from_skipped_shards() -> None:
    summary = summarize_shards(
        [
            ShardOutcome(status=RunStatus.SUCCESS, coverage_complete=False),
            ShardOutcome(status=RunStatus.FAILED, coverage_complete=False),
            ShardOutcome(status=SHARD_STATUS_SKIPPED, coverage_complete=False),
            ShardOutcome(status=SHARD_STATUS_SKIPPED, coverage_complete=False),
        ]
    )

    assert summary.run_status == RunStatus.PARTIAL
    assert summary.coverage_status == CoverageStatus.DEGRADED
    assert summary.shards_failed == 1
    assert summary.shards_skipped == 2


def test_paused_run_can_never_claim_authoritative_coverage() -> None:
    summary = summarize_shards(
        [
            ShardOutcome(status=RunStatus.SUCCESS, coverage_complete=True),
            ShardOutcome(status=RUN_STATUS_PAUSED, coverage_complete=False),
            ShardOutcome(status=RunStatus.RUNNING, coverage_complete=False),
        ]
    )

    assert summary.run_status == RUN_STATUS_PAUSED
    assert summary.coverage_status == CoverageStatus.DEGRADED
    assert summary.shards_paused == 1
    assert summary.shards_failed == 0


def test_empty_source_is_failure_not_false_success() -> None:
    summary = summarize_shards([])

    assert summary.run_status == RunStatus.FAILED
    assert summary.coverage_status == CoverageStatus.FAILED



class _CreateRunSession:
    def __init__(self) -> None:
        self.added = []
        self.commits = 0

    def scalars(self, _statement):
        return []

    def add(self, value) -> None:
        self.added.append(value)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


def test_create_run_carries_manual_request_id_from_runner_environment(monkeypatch) -> None:
    session = _CreateRunSession()
    source = type("SourceStub", (), {"id": 17})()
    monkeypatch.setenv("WOHNWERK_MANUAL_RUN_REQUEST_ID", "manual-test-123")

    run = create_run(session, source, CrawlMode.INCREMENTAL)

    assert run.run_metadata == {"manual_run_request_id": "manual-test-123"}
    assert session.commits == 1
