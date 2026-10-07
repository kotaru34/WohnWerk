from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, async_playwright

from app.crawling.immowelt_operator_handoff import (
    live_operator_session,
    register_live_operator_session,
    unregister_live_operator_session,
)
from app.sources.base import SourceChallenge, SourceFetchError
from app.sources.property.immowelt_de import (
    ImmoweltGermanyPropertySource,
    _canonical_expose_url,
)


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
        pending_viewport = getattr(self, "_pending_viewport", None)
        if isinstance(pending_viewport, dict):
            context_kwargs["viewport"] = dict(pending_viewport)
        storage_state_path = getattr(self, "_pending_storage_state_path", None)
        if storage_state_path and Path(storage_state_path).is_file():
            context_kwargs["storage_state"] = storage_state_path
        pending_user_agent = getattr(self, "_pending_user_agent", None)
        if pending_user_agent:
            context_kwargs["user_agent"] = str(pending_user_agent)
        self._context = await self._browser.new_context(**context_kwargs)
        self._page = await self._context.new_page()
        return self._page

    async def aclose(self) -> None:
        live_state_dir = getattr(self, "_live_operator_state_dir", None)
        if live_state_dir is not None:
            unregister_live_operator_session(
                Path(live_state_dir),
                page=self._page,
            )
            self._live_operator_state_dir = None
        await super().aclose()

    async def _load_html(self, url: str) -> tuple[str, str]:
        if getattr(self, "_reuse_current_page_once", False) and self._page is not None:
            self._reuse_current_page_once = False
            page = self._page
            challenge = await self._challenge_probe(
                page=page,
                requested_url=url,
                status=200,
            )
            if challenge is not None:
                raise SourceChallenge(
                    f"Immowelt access challenge detected ({challenge['kind']})",
                    challenge=challenge,
                )
            host = __import__("urllib.parse").parse.urlparse(page.url).hostname or ""
            if host.casefold() in {"immowelt.de", "www.immowelt.de"}:
                expected = __import__("urllib.parse").parse.urlparse(url)
                actual = __import__("urllib.parse").parse.urlparse(page.url)
                if expected.path == actual.path and expected.query == actual.query:
                    if await page.locator("h1").count() > 0:
                        return await page.content(), page.url
        return await super()._load_html(url)

    async def load_detail_html(self, url: str) -> tuple[str, str]:
        """Load one exact public Immowelt expose through the active headed session.

        This deliberately reuses the crawl browser context so a clearance already
        established for the search run also applies to the bounded heating lookup.
        It never solves a newly encountered challenge here; callers must fail soft.
        """
        canonical = _canonical_expose_url(url)
        if canonical is None:
            raise ValueError(f"Unsupported Immowelt detail URL: {url!r}")
        requested_url, listing_id = canonical

        if self._requests_made:
            await self._sleep()
        self._requests_made += 1

        page = await self._ensure_page()
        response = await page.goto(
            requested_url,
            wait_until="domcontentloaded",
            timeout=int(self.timeout_seconds * 1000),
        )
        if response is None:
            raise RuntimeError("Immowelt detail navigation returned no response")

        status = response.status
        challenge = await self._challenge_probe(
            page=page,
            requested_url=requested_url,
            status=status,
        )
        if challenge is not None:
            raise SourceChallenge(
                f"Immowelt detail access challenge detected ({challenge['kind']})",
                challenge=challenge,
            )
        if status == 429:
            raise SourceFetchError("Immowelt detail HTTP 429 rate limit", halt_source=True)
        if status >= 400:
            raise RuntimeError(f"Immowelt detail HTTP {status}")

        final = _canonical_expose_url(page.url)
        if final is None or final[1] != listing_id:
            raise RuntimeError(f"Immowelt detail redirected unexpectedly: {page.url!r}")

        await page.wait_for_selector("h1", timeout=int(self.timeout_seconds * 1000))
        await page.wait_for_timeout(500)

        challenge = await self._challenge_probe(
            page=page,
            requested_url=requested_url,
            status=status,
        )
        if challenge is not None:
            raise SourceChallenge(
                f"Immowelt detail access challenge detected ({challenge['kind']})",
                challenge=challenge,
            )
        return await page.content(), page.url

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
        user_agent: str | None = None
        viewport: dict[str, int] | None = None
        if self._page is not None:
            try:
                user_agent = str(await self._page.evaluate("navigator.userAgent"))
            except PlaywrightError:
                user_agent = None
            try:
                raw_viewport = await self._page.evaluate(
                    "() => ({width: window.innerWidth, height: window.innerHeight})"
                )
                if isinstance(raw_viewport, dict):
                    viewport = {
                        "width": int(raw_viewport["width"]),
                        "height": int(raw_viewport["height"]),
                    }
            except (KeyError, TypeError, ValueError, PlaywrightError):
                viewport = None
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
        if user_agent:
            handoff["user_agent"] = user_agent
        if viewport:
            handoff["viewport"] = viewport
        if screenshot_path and str(screenshot_path) != ".":
            handoff["screenshot_path"] = str(screenshot_path)
        if self._context is not None and self._page is not None:
            register_live_operator_session(
                state_dir,
                context=self._context,
                page=self._page,
            )
            self._live_operator_state_dir = state_dir
        return handoff

    async def restore_challenge_handoff(self, handoff_state: dict[str, Any]) -> None:
        state_dir_raw = handoff_state.get("state_dir")
        if not state_dir_raw:
            raise RuntimeError("Challenge handoff state directory is missing")
        state_dir = Path(str(state_dir_raw)).resolve()
        raw_viewport = handoff_state.get("viewport")
        if isinstance(raw_viewport, dict):
            try:
                width = int(raw_viewport.get("width"))
                height = int(raw_viewport.get("height"))
            except (TypeError, ValueError):
                width = height = 0
            if 320 <= width <= 4096 and 240 <= height <= 2160:
                self._pending_viewport = {"width": width, "height": height}

        def _confined_path(key: str) -> Path | None:
            raw = handoff_state.get(key)
            if not raw:
                return None
            candidate = Path(str(raw)).resolve()
            try:
                candidate.relative_to(state_dir)
            except ValueError as exc:
                raise RuntimeError(
                    f"Challenge handoff path escaped state directory: {key}"
                ) from exc
            return candidate

        _confined_path("screenshot_path")
        path = _confined_path("storage_state_path")
        if path is not None:
            if not path.is_file():
                raise RuntimeError(f"Challenge storage state is missing: {path}")
            self._pending_storage_state_path = str(path)
            handoff_user_agent = str(handoff_state.get("user_agent") or "").strip()
            if handoff_user_agent:
                self._pending_user_agent = handoff_user_agent

        patch_applied = False
        patch_path = _confined_path("browser_patch_path")
        if patch_path is not None and patch_path.is_file():
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
                patch_applied = True

        live = live_operator_session(state_dir)
        if (
            not patch_applied
            and live is not None
            and self._context is live.context
            and self._page is live.page
        ):
            self._reuse_current_page_once = True
            return

        if self._page is not None:
            await self._page.close()
            self._page = None
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
