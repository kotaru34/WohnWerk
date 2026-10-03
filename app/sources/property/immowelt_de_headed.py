from __future__ import annotations

import json
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
        pending_user_agent = getattr(self, "_pending_user_agent", None)
        if pending_user_agent:
            context_kwargs["user_agent"] = str(pending_user_agent)
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
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        state_dir.chmod(0o700)
        storage_state_path = state_dir / "storage-state.json"
        screenshot_path = state_dir / "challenge.png"
        browser_patch_path = state_dir / "browser-patch.json"

        if self._context is not None:
            await self._context.storage_state(path=str(storage_state_path))
            storage_state_path.chmod(0o600)
        if self._page is not None:
            try:
                await self._page.screenshot(path=str(screenshot_path), full_page=True)
                screenshot_path.chmod(0o600)
            except PlaywrightError:
                screenshot_path = Path()

        handoff: dict[str, Any] = {
            "state_dir": str(state_dir),
            "storage_state_path": str(storage_state_path),
            "current_url": self._page.url if self._page is not None else None,
            "browser_patch_path": str(browser_patch_path),
            "challenge": dict(challenge.challenge),
        }
        if screenshot_path and str(screenshot_path) != ".":
            handoff["screenshot_path"] = str(screenshot_path)
        return handoff

    async def restore_challenge_handoff(self, handoff_state: dict[str, Any]) -> None:
        storage_state = handoff_state.get("storage_state_path")
        path: Path | None = None
        if storage_state:
            path = Path(str(storage_state))
            if not path.is_file():
                raise RuntimeError(f"Challenge storage state is missing: {path}")
            self._pending_storage_state_path = str(path)

        browser_patch = handoff_state.get("browser_patch_path")
        if browser_patch:
            patch_path = Path(str(browser_patch))
            if patch_path.is_file():
                if path is None:
                    raise RuntimeError("Browser patch cannot be applied without storage state")
                try:
                    patch = json.loads(patch_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Invalid challenge browser patch JSON: {patch_path}") from exc
                if (
                    not isinstance(patch, dict)
                    or patch.get("version") != 1
                    or patch.get("kind") != "immowelt_datadome_clearance"
                ):
                    raise RuntimeError("Unsupported challenge browser patch")
                user_agent = str(patch.get("user_agent") or "").strip()
                cookie = patch.get("cookie")
                if not user_agent or not isinstance(cookie, dict):
                    raise RuntimeError("Incomplete DataDome browser patch")
                if cookie.get("name") != "datadome":
                    raise RuntimeError("Challenge browser patch contains unexpected cookie")
                domain = str(cookie.get("domain") or "").casefold().lstrip(".")
                if domain not in {"immowelt.de", "www.immowelt.de"} and not domain.endswith(
                    ".immowelt.de"
                ):
                    raise RuntimeError("Challenge browser patch cookie is not scoped to Immowelt")

                try:
                    state = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Invalid challenge storage state JSON: {path}") from exc
                cookies = list(state.get("cookies") or [])

                def _immowelt_cookie_domain(value: object) -> bool:
                    normalized = str(value or "").casefold().lstrip(".")
                    return normalized in {"immowelt.de", "www.immowelt.de"} or normalized.endswith(
                        ".immowelt.de"
                    )

                cookies = [
                    item
                    for item in cookies
                    if not (
                        isinstance(item, dict)
                        and item.get("name") == "datadome"
                        and _immowelt_cookie_domain(item.get("domain"))
                    )
                ]
                cookies.append(dict(cookie))
                state["cookies"] = cookies
                path.write_text(
                    json.dumps(state, ensure_ascii=False, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                path.chmod(0o600)
                self._pending_user_agent = user_agent
                patch_path.unlink()

        if self._page is not None:
            await self._page.close()
            self._page = None
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
