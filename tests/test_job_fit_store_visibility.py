from app.jobs.fit_store import _listing_is_catalog_eligible
from app.models import JobListing, ListingStatus


def _listing(*, source_id: int = 7, status: ListingStatus = ListingStatus.ACTIVE, accepted: bool = True) -> JobListing:
    return JobListing(
        source_id=source_id,
        source_listing_id="example",
        url="https://example.invalid/job",
        status=status,
        raw_payload={
            "wohnwerk_discovery_gate": {
                "version": "test",
                "accepted": accepted,
            }
        },
    )


def test_enabled_active_accepted_listing_is_catalog_eligible() -> None:
    assert _listing_is_catalog_eligible(_listing(), {7}) is True


def test_disabled_source_listing_is_not_catalog_eligible() -> None:
    assert _listing_is_catalog_eligible(_listing(), set()) is False


def test_rejected_listing_is_not_catalog_eligible() -> None:
    assert _listing_is_catalog_eligible(_listing(accepted=False), {7}) is False


def test_inactive_listing_is_not_catalog_eligible() -> None:
    assert (
        _listing_is_catalog_eligible(
            _listing(status=ListingStatus.INACTIVE),
            {7},
        )
        is False
    )
