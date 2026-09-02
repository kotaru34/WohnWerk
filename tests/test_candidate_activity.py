from datetime import UTC, datetime, timedelta

from app.candidate_activity import is_new_unviewed


def test_existing_unviewed_item_is_not_new_at_rollout_baseline() -> None:
    baseline = datetime(2026, 8, 28, 20, 0, tzinfo=UTC)

    assert (
        is_new_unviewed(
            first_seen_at=baseline - timedelta(days=1),
            baseline=baseline,
            viewed_at=None,
        )
        is False
    )
    assert (
        is_new_unviewed(
            first_seen_at=baseline,
            baseline=baseline,
            viewed_at=None,
        )
        is False
    )


def test_post_rollout_unviewed_item_is_new_until_viewed() -> None:
    baseline = datetime(2026, 8, 28, 20, 0, tzinfo=UTC)
    first_seen = baseline + timedelta(seconds=1)

    assert is_new_unviewed(first_seen_at=first_seen, baseline=baseline, viewed_at=None) is True
    assert (
        is_new_unviewed(
            first_seen_at=first_seen,
            baseline=baseline,
            viewed_at=first_seen + timedelta(minutes=2),
        )
        is False
    )
