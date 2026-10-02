from __future__ import annotations

from typing import Any

import httpx
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app.sources.base import SourceFetchError
from app.sources.property.von_poll_de import (
    _ALLOWED_HOSTS,
    _RETRYABLE_STATUSES,
    VonPollGermanyPropertySource,
)


class VonPollHeadedPropertySource(VonPollGermanyPropertySource):
    """VON POLL transport using the server's ordinary headed Chromium session."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def _ensure_page(self) -> Page:
        if self._page is not None:
            return self._page

        if self._playwright is None:
            self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=False,
            args=["--disable-crash-reporter"],
        )
        self._context = await self._browser.new_context(locale="de-DE")

        async def block_heavy_assets(route: Any) -> None:
            if route.request.resource_type in {"font", "image", "media"}:
                await route.abort()
            else:
                await route.continue_()

        await self._context.route("**/*", block_heavy_assets)
        self._page = await self._context.new_page()
        return self._page

    async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        del client
        if self._requests_made:
            await self._sleep()
        self._requests_made += 1

        page = await self._ensure_page()
        last_status = 0
        for attempt in range(3):
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=max(1, int(self.timeout_seconds * 1000)),
            )
            last_status = response.status if response is not None else 0
            host = (httpx.URL(page.url).host or "").casefold()
            if host not in _ALLOWED_HOSTS:
                raise RuntimeError(f"VON POLL redirected off-site: {page.url!s}")

            if last_status in {401, 403}:
                raise SourceFetchError(
                    f"VON POLL access gate HTTP {last_status}",
                    halt_source=True,
                )
            if last_status < 400:
                return httpx.Response(
                    last_status,
                    text=await page.content(),
                    request=httpx.Request("GET", page.url),
                )
            if attempt == 2 or last_status not in _RETRYABLE_STATUSES:
                raise SourceFetchError(
                    f"VON POLL browser HTTP {last_status}",
                    halt_source=last_status in {401, 403},
                )
            await self._sleep()

        raise SourceFetchError(f"VON POLL browser HTTP {last_status}")

    async def aclose(self) -> None:
        if self._page is not None:
            await self._page.close()
            self._page = None
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
