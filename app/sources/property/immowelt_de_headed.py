from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, async_playwright

from app.sources.base import SourceChallenge
from app.sources.property.immowelt_de import ImmoweltGermanyPropertySource


class ImmoweltHeadedPropertySource(ImmoweltGermanyPropertySource):
    """Immowelt adapter using ordinary headed Chromium on an X display.

    Challenge detection and crawl orchestration live in the base adapter/runner. This class
    only exposes browser state at a persisted handoff boundary so an operator-provided
    external handler can act, then reloads the returned storage state before WohnWerk
    retries the exact navigation point. No challenge-solving implementation lives here.
    """

    async def _ensure_page(self) -> Page:
        if self._page is not None:
            return self._page

        if self._playwright is None:
            self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=False,
            args=["--disable-crash-reporter"],
        )
        context_kwargs: dict[str, Any] = {"locale": "de-DE"}
        storage_state_path = getattr(self, "_pending_storage_state_path", None)
        if storage_state_path and Path(storage_state_path).is_file():
            context_kwargs["storage_state"] = storage_state_path
        self._context = await self._browser.new_context(**context_kwargs)

        async def block_heavy_assets(route: Any) -> None:
            if route.request.resource_type in {"font", "image", "media"}:
                await route.abort()
            else:
                await route.continue_()

        await self._context.route("**/*", block_heavy_assets)
        self._page = await self._context.new_page()
        return self._page

    async def prepare_challenge_handoff(
        self,
        *,
        state_dir: Path,
        challenge: SourceChallenge,
    ) -> dict[str, Any]:
        state_dir.mkdir(parents=True, exist_ok=True)
        storage_state_path = state_dir / "storage-state.json"
        screenshot_path = state_dir / "challenge.png"

        if self._context is not None:
            await self._context.storage_state(path=str(storage_state_path))
        if self._page is not None:
            try:
                await self._page.screenshot(path=str(screenshot_path), full_page=True)
            except PlaywrightError:
                screenshot_path = Path()

        handoff: dict[str, Any] = {
            "state_dir": str(state_dir),
            "storage_state_path": str(storage_state_path),
            "current_url": self._page.url if self._page is not None else None,
            "challenge": dict(challenge.challenge),
        }
        if screenshot_path and str(screenshot_path) != ".":
            handoff["screenshot_path"] = str(screenshot_path)
        return handoff

    async def restore_challenge_handoff(self, handoff_state: dict[str, Any]) -> None:
        storage_state = handoff_state.get("storage_state_path")
        if storage_state:
            path = Path(str(storage_state))
            if not path.is_file():
                raise RuntimeError(f"Challenge storage state is missing: {path}")
            self._pending_storage_state_path = str(path)

        if self._page is not None:
            await self._page.close()
            self._page = None
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
