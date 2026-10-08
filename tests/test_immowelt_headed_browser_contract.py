from __future__ import annotations

import pytest

import app.sources.property.immowelt_de_headed as headed


@pytest.mark.asyncio
async def test_immowelt_live_adapter_uses_headed_browser_without_asset_interception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline regression guard: the actual crawler is not the headless base class."""
    calls: list[tuple[str, object]] = []

    class Page:
        async def close(self) -> None:
            calls.append(("close-page", None))

    class Context:
        async def new_page(self) -> Page:
            calls.append(("new-page", None))
            return Page()

        async def route(self, *_args: object) -> None:
            raise AssertionError("Live human challenge must not silently block resources")

        async def close(self) -> None:
            calls.append(("close-context", None))

    class Browser:
        async def new_context(self, **kwargs: object) -> Context:
            calls.append(("new-context", kwargs))
            return Context()

        async def close(self) -> None:
            calls.append(("close-browser", None))

    class Chromium:
        async def launch(self, **kwargs: object) -> Browser:
            calls.append(("launch", kwargs))
            return Browser()

    class Playwright:
        chromium = Chromium()

        async def stop(self) -> None:
            calls.append(("stop-playwright", None))

    class Starter:
        async def start(self) -> Playwright:
            return Playwright()

    monkeypatch.setattr(headed, "async_playwright", lambda: Starter())
    adapter = headed.ImmoweltHeadedPropertySource()
    try:
        page = await adapter._ensure_page()
        assert isinstance(page, Page)
        assert ("launch", {"headless": False, "args": ["--disable-crash-reporter"]}) in calls
        assert ("new-context", {"locale": "de-DE"}) in calls
        assert sum(event == "new-page" for event, _value in calls) == 1
    finally:
        await adapter.aclose()
