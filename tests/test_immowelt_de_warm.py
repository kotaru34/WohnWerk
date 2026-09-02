from __future__ import annotations

import pytest

from app.sources.property.immowelt_de_warm import ImmoweltWarmSessionPropertySource


def test_ui_entry_resolves_region_serp() -> None:
    source = ImmoweltWarmSessionPropertySource()

    sachsen = source._page_url("sachsen", "030000-149999", 1)
    berlin = source._page_url("berlin", "150000-224999", 1)

    assert source._warmup_url(sachsen) == (
        "https://www.immowelt.de/suche/kaufen/haus/sachsen/ad04de14"
    )
    assert source._warmup_url(berlin) == (
        "https://www.immowelt.de/suche/kaufen/haus/berlin/ad08de8634"
    )


def test_search_state_helpers_keep_exact_shard_and_page() -> None:
    source = ImmoweltWarmSessionPropertySource()
    requested = source._page_url("sachsen", "030000-149999", 1)

    assert source._search_key(requested) == (
        "Buy,Buy_Auction,Compulsory_Auction",
        "House",
        "AD04DE14",
        "30000",
        "149999",
        "DateDesc",
    )
    assert source._requested_page(requested) == 1

    page2 = source._with_page(requested, 2)
    assert source._requested_page(page2) == 2
    assert source._search_key(page2) == source._search_key(requested)
    assert "page=2" in page2


class FakePage:
    def __init__(self) -> None:
        self.url = "about:blank"

    async def content(self) -> str:
        return "<html><body><h1>1 Haus zum Kauf</h1></body></html>"


class ProbeSource(ImmoweltWarmSessionPropertySource):
    def __init__(self) -> None:
        super().__init__(request_delay_seconds=1.0)
        self.fake_page = FakePage()
        self.events: list[tuple[str, int]] = []

    async def _ensure_page(self) -> FakePage:
        return self.fake_page

    async def _sleep(self) -> None:
        return None

    async def _assert_public_page(self) -> None:
        return None

    async def _establish_page_one(self, requested_url: str) -> None:
        page1 = self._with_page(requested_url, 1)
        self.fake_page.url = page1
        self._active_search_key = self._search_key(page1)
        self._active_page = 1
        self.events.append(("establish", 1))

    async def _advance_to_page(self, requested_url: str, target_page: int) -> None:
        self.fake_page.url = self._with_page(requested_url, target_page)
        self._active_page = target_page
        self.events.append(("advance", target_page))


@pytest.mark.asyncio
async def test_load_html_uses_ui_state_machine_instead_of_direct_navigation() -> None:
    source = ProbeSource()
    page1 = source._page_url("sachsen", "030000-149999", 1)
    page2 = source._page_url("sachsen", "030000-149999", 2)

    html1, final1 = await source._load_html(page1)
    html2, final2 = await source._load_html(page2)

    assert "1 Haus zum Kauf" in html1
    assert "1 Haus zum Kauf" in html2
    assert source.events == [("establish", 1), ("advance", 2)]
    assert final1 == source._with_page(page1, 1)
    assert final2 == source._with_page(page2, 2)
    assert source._requests_made == 2


@pytest.mark.asyncio
async def test_requesting_page_one_again_reestablishes_ui_state() -> None:
    source = ProbeSource()
    page1 = source._page_url("sachsen", "030000-149999", 1)

    await source._load_html(page1)
    await source._load_html(page1)

    assert source.events == [("establish", 1), ("establish", 1)]
