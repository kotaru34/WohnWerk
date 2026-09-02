from __future__ import annotations

import pytest

from app.sources.property.immowelt_de_warm import ImmoweltWarmSessionPropertySource


class FakeResponse:
    status = 200


class FakePage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.visited: list[str] = []
        self.waited_for: list[str] = []
        self.waited_ms: list[int] = []

    async def goto(self, url: str, **_: object) -> FakeResponse:
        self.url = url
        self.visited.append(url)
        return FakeResponse()

    async def wait_for_selector(self, selector: str, **_: object) -> None:
        self.waited_for.append(selector)

    async def wait_for_timeout(self, milliseconds: int) -> None:
        self.waited_ms.append(milliseconds)


class ProbeSource(ImmoweltWarmSessionPropertySource):
    def __init__(self) -> None:
        super().__init__(request_delay_seconds=1.0)
        self.fake_page = FakePage()

    async def _ensure_page(self) -> FakePage:
        return self.fake_page


@pytest.mark.asyncio
async def test_warmup_enters_public_region_serp_once() -> None:
    source = ProbeSource()
    requested = source._page_url("sachsen", "030000-149999", 1)

    assert source._warmup_url(requested) == (
        "https://www.immowelt.de/suche/kaufen/haus/sachsen/ad04de14"
    )

    await source._prime_search_context(requested)
    await source._prime_search_context(requested)

    assert source.fake_page.visited == [
        "https://www.immowelt.de/suche/kaufen/haus/sachsen/ad04de14"
    ]
    assert source.fake_page.waited_for == ["h1"]
    assert source._search_context_primed is True
    assert source._requests_made == 1


def test_warmup_resolves_city_state_location_id() -> None:
    source = ImmoweltWarmSessionPropertySource()
    requested = source._page_url("berlin", "150000-224999", 1)

    assert source._warmup_url(requested) == (
        "https://www.immowelt.de/suche/kaufen/haus/berlin/ad08de8634"
    )
