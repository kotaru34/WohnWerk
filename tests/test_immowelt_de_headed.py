from __future__ import annotations

import pytest

import app.sources.property.immowelt_de_headed as headed_module
from app.sources.property.immowelt_de_headed import ImmoweltHeadedPropertySource


class FakeRouteTarget:
    async def route(self, pattern: str, handler: object) -> None:
        self.pattern = pattern
        self.handler = handler

    async def new_page(self) -> object:
        return object()


class FakeBrowser:
    def __init__(self) -> None:
        self.context = FakeRouteTarget()
        self.context_kwargs: dict[str, object] | None = None

    async def new_context(self, **kwargs: object) -> FakeRouteTarget:
        self.context_kwargs = kwargs
        return self.context


class FakeChromium:
    def __init__(self) -> None:
        self.launch_kwargs: dict[str, object] | None = None
        self.browser = FakeBrowser()

    async def launch(self, **kwargs: object) -> FakeBrowser:
        self.launch_kwargs = kwargs
        return self.browser


class FakePlaywright:
    def __init__(self) -> None:
        self.chromium = FakeChromium()


class FakeStarter:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright

    async def start(self) -> FakePlaywright:
        return self.playwright


@pytest.mark.asyncio
async def test_immowelt_launches_plain_headed_chromium(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePlaywright()
    monkeypatch.setattr(
        headed_module,
        "async_playwright",
        lambda: FakeStarter(fake),
    )

    source = ImmoweltHeadedPropertySource()
    page = await source._ensure_page()

    assert page is not None
    assert fake.chromium.launch_kwargs == {
        "headless": False,
        "args": ["--disable-crash-reporter"],
    }
    assert fake.chromium.browser.context_kwargs == {"locale": "de-DE"}
    assert fake.chromium.browser.context.pattern == "**/*"


def test_headed_adapter_keeps_confirmed_direct_search_urls() -> None:
    source = ImmoweltHeadedPropertySource()
    url = source._page_url("sachsen", "030000-149999", 1)

    assert url.startswith("https://www.immowelt.de/classified-search?")
    assert "locations=AD04DE14" in url
    assert "priceMin=30000" in url
    assert "priceMax=149999" in url
    assert "order=DateDesc" in url
    assert "page=1" in url
