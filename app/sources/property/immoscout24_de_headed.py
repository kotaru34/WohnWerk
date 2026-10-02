from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, async_playwright

from app.sources.base import SourceChallenge
from app.sources.property.immoscout24_de import ImmoScout24GermanyPropertySource


class ImmoScout24HeadedPropertySource(ImmoScout24GermanyPropertySource):
    """ImmoScout transport that exposes browser state for operator challenge handoff."""

    async def _ensure_browser_context(self) -> BrowserContext:
        if self._browser_context is not None:
            return self._browser_context

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
        self._browser_context = await self._browser.new_context(**context_kwargs)

        async def block_heavy_assets(route: Any) -> None:
            if route.request.resource_type in {"font", "image", "media"}:
                await route.abort()
            else:
                await route.continue_()

        await self._browser_context.route("**/*", block_heavy_assets)
        return self._browser_context

    async def prepare_challenge_handoff(
        self,
        *,
        state_dir: Path,
        challenge: SourceChallenge,
    ) -> dict[str, Any]:
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        state_dir.chmod(0o700)
        storage_state_path = state_dir / "storage-state.json"

        if self._browser_context is not None:
            await self._browser_context.storage_state(path=str(storage_state_path))
            storage_state_path.chmod(0o600)

        return {
            "state_dir": str(state_dir),
            "storage_state_path": str(storage_state_path),
            "current_url": challenge.challenge.get("final_url")
            or challenge.challenge.get("requested_url"),
            "challenge": dict(challenge.challenge),
        }

    async def restore_challenge_handoff(self, handoff_state: dict[str, Any]) -> None:
        storage_state = handoff_state.get("storage_state_path")
        if storage_state:
            path = Path(str(storage_state))
            if not path.is_file():
                raise RuntimeError(f"Challenge storage state is missing: {path}")
            self._pending_storage_state_path = str(path)

        if self._browser_context is not None:
            await self._browser_context.close()
            self._browser_context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
