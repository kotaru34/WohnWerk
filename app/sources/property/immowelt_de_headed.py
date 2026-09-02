from __future__ import annotations

from typing import Any

from playwright.async_api import Page, async_playwright

from app.sources.property.immowelt_de import ImmoweltGermanyPropertySource


class ImmoweltHeadedPropertySource(ImmoweltGermanyPropertySource):
    """Immowelt adapter using ordinary headed Chromium on an X display.

    The public Immowelt ``/classified-search`` route is accepted by headed
    Chromium on the target host but returns HTTP 403 in Chromium headless mode.
    Keep the proven direct search URLs and parser; only the browser execution
    mode differs. No stealth flags, CAPTCHA handling, login, persisted browser
    profile, or private session state are used.
    """

    async def _ensure_page(self) -> Page:
        if self._page is not None:
            return self._page

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
