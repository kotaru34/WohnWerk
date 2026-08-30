from app.sources.base import SourceBatch


def test_source_batch_never_reports_fewer_rows_than_it_materialized() -> None:
    batch = SourceBatch(
        items=["a", "b", "c"],
        source_reported_count=0,
        pages_fetched=2,
    )

    assert batch.source_reported_count == 3


def test_source_batch_preserves_larger_provider_total() -> None:
    batch = SourceBatch(
        items=["a", "b"],
        source_reported_count=17,
    )

    assert batch.source_reported_count == 17


def test_source_batch_preserves_unknown_provider_total() -> None:
    batch = SourceBatch(
        items=["a"],
        source_reported_count=None,
    )

    assert batch.source_reported_count is None
