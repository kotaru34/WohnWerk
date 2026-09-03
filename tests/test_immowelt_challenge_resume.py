from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from app.sources.base import SourceChallenge
from app.sources.property.immowelt_de import (
    ImmoweltGermanyPropertySource,
    detect_immowelt_challenge,
)


def _one_card_html(*, total: int = 1, listing_id: str = "26zklwh9fcdf") -> str:
    return f"""
    <html><body>
      <h1>{total} Häuser zum Kauf in Sachsen</h1>
      <div data-testid="serp-core-classified-card-testid">
        <a data-testid="card-mfe-covering-link-testid"
           href="https://www.immowelt.de/expose/{listing_id}"
           title="Haus zum Kauf - Dresden - 149.500 € - 4 Zimmer, 98 m², 300 m² Grundstück"></a>
        <div data-testid="cardmfe-description-box-address">01067 Dresden</div>
      </div>
    </body></html>
    """


def test_direct_403_is_explicit_challenge() -> None:
    challenge = detect_immowelt_challenge(
        status=403,
        requested_url="https://www.immowelt.de/classified-search?page=2",
        final_url="https://www.immowelt.de/classified-search?page=2",
        html="<html></html>",
    )

    assert challenge is not None
    assert challenge["kind"] == "http_403"
    assert challenge["http_status"] == 403


def test_known_challenge_frame_is_detected_even_with_http_200() -> None:
    challenge = detect_immowelt_challenge(
        status=200,
        requested_url="https://www.immowelt.de/classified-search?page=2",
        final_url="https://www.immowelt.de/classified-search?page=2",
        html="<html><body></body></html>",
        frame_urls=["https://geo.captcha-delivery.com/captcha/?id=example"],
    )

    assert challenge is not None
    assert challenge["kind"] == "challenge_frame_or_redirect"


def test_normal_search_document_is_not_false_positive() -> None:
    challenge = detect_immowelt_challenge(
        status=200,
        requested_url="https://www.immowelt.de/classified-search?page=1",
        final_url="https://www.immowelt.de/classified-search?page=1",
        html=_one_card_html(),
    )

    assert challenge is None


@pytest.mark.asyncio
async def test_challenge_persists_exact_shard_band_state_and_retry_page() -> None:
    class Challenged(ImmoweltGermanyPropertySource):
        async def _load_html(self, url: str) -> tuple[str, str]:
            raise SourceChallenge(
                "Immowelt access challenge detected (http_403)",
                challenge={
                    "kind": "http_403",
                    "http_status": 403,
                    "requested_url": url,
                    "final_url": url,
                },
            )

    source = Challenged(request_delay_seconds=1.0)
    shard = next(
        shard
        for shard in source.default_shards()
        if shard.key == "sachsen:030000-149999"
    )

    with pytest.raises(SourceChallenge) as caught:
        await source.fetch_shard(shard, reconciliation=False)

    exc = caught.value
    assert exc.challenge["region_key"] == "sachsen"
    assert exc.challenge["bundesland"] == "Sachsen"
    assert exc.challenge["price_band_key"] == "030000-149999"
    assert exc.challenge["page"] == 1
    assert exc.next_cursor["_resume_same_run"] is True
    assert exc.next_cursor["resume_page"] == 1
    assert exc.next_cursor["discovery_completed_pages"] == 0
    assert exc.next_cursor["discovery_seen_ids"] == []
    assert exc.next_cursor["discovery_identity_history_complete"] is True


@pytest.mark.asyncio
async def test_same_run_resume_starts_at_saved_page_not_page_one() -> None:
    class Probe(ImmoweltGermanyPropertySource):
        def __init__(self) -> None:
            super().__init__(request_delay_seconds=1.0)
            self.requested_pages: list[int] = []

        async def _load_html(self, url: str) -> tuple[str, str]:
            page = int(parse_qs(urlparse(url).query)["page"][0])
            self.requested_pages.append(page)
            return _one_card_html(total=41, listing_id="36zklwh9fcdf"), url

    source = Probe()
    shard = next(
        shard
        for shard in source.default_shards()
        if shard.key == "sachsen:030000-149999"
    )
    resume_cursor = {
        "_resume_same_run": True,
        "resume_page": 2,
        "discovery_completed_pages": 1,
        "discovery_target_pages": 2,
        "discovery_cards_seen": 40,
        "discovery_cards_parsed": 40,
        "discovery_cards_total": 40,
        "discovery_project_cards_skipped": 0,
        "discovery_blank_cards_skipped": 0,
        "discovery_max_page": 2,
        "discovery_initial_reported_count": 41,
        "discovery_latest_reported_count": 41,
        "discovery_max_reported_count": 41,
        "discovery_seen_ids": [f"saved-{index}" for index in range(40)],
    }

    batch = await source.fetch_shard(
        shard,
        cursor=resume_cursor,
        reconciliation=True,
    )

    assert source.requested_pages == [2]
    assert batch.pages_fetched == 1
    assert batch.next_cursor["discovery_completed_pages"] == 2
    assert batch.next_cursor["discovery_unique_ids_seen"] == 41
    assert batch.coverage_complete is True
    assert batch.next_cursor["discovery_count_delta"] == 0


@pytest.mark.asyncio
async def test_legacy_resume_without_identity_history_cannot_gain_reconciliation_authority() -> None:
    class Probe(ImmoweltGermanyPropertySource):
        async def _load_html(self, url: str) -> tuple[str, str]:
            return _one_card_html(total=41, listing_id="46zklwh9fcdf"), url

    source = Probe(request_delay_seconds=1.0)
    shard = next(
        shard
        for shard in source.default_shards()
        if shard.key == "sachsen:030000-149999"
    )
    legacy_cursor = {
        "_resume_same_run": True,
        "resume_page": 2,
        "discovery_completed_pages": 1,
        "discovery_target_pages": 2,
        "discovery_cards_seen": 40,
        "discovery_cards_parsed": 40,
        "discovery_cards_total": 40,
        "discovery_project_cards_skipped": 0,
        "discovery_blank_cards_skipped": 0,
        "discovery_max_page": 2,
        "discovery_initial_reported_count": 41,
        "discovery_latest_reported_count": 41,
        "discovery_max_reported_count": 41,
    }

    batch = await source.fetch_shard(shard, cursor=legacy_cursor, reconciliation=True)

    assert batch.next_cursor["discovery_identity_history_complete"] is False
    assert batch.coverage_complete is False
