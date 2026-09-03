from __future__ import annotations

import asyncio
import math
import random
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.sources.base import RawProperty, SourceBatch, SourceFetchError, SourceShardSpec
from app.sources.property.challenge_control import (
    ChallengeAction,
    ChallengeHandler,
    ChallengeRequest,
    invoke_challenge_handler,
    persist_browser_state,
)
from app.sources.property.immowelt_de import (
    CARD_TEST_ID,
    PAGE_SIZE,
    PRICE_BANDS_BY_KEY,
    REGIONS_BY_KEY,
    ImmoweltGermanyPropertySource,
    _validate_page,
    _validate_search_state,
    parse_immowelt_search_page,
)
from app.sources.property.immowelt_de_headed import ImmoweltHeadedPropertySource

CheckpointCallback = Callable[[dict[str, Any]], Awaitable[None]]

_CHALLENGE_TEXT_MARKERS = (
    "ich bin kein roboter",
    "verify you are human",
    "bestätigen sie, dass sie ein mensch sind",
    "captcha",
    "access denied",
    "zugriff verweigert",
)
_CHALLENGE_HTML_MARKERS = (
    "captcha-delivery.com",
    "datadome",
    "geo.captcha-delivery.com",
)
_CHALLENGE_URL_MARKERS = ("captcha", "challenge")


class ImmoweltChallengeDeferred(SourceFetchError):
    """A challenge handoff was unavailable or deliberately deferred.

    This is not an acquisition/parser failure. The property runner records the current
    shard and untouched remainder as skipped, while preserving degraded/non-authoritative
    coverage. A later normal scheduler run can try the fair frontier again.
    """

    deferred_source = True

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, halt_source=True, **kwargs)


def classify_immowelt_challenge(
    *,
    http_status: int | None,
    final_url: str,
    visible_text: str,
    html: str,
) -> str | None:
    """Return a concrete challenge reason, or None for an ordinary response."""
    if http_status == 403:
        return "http_403"

    lowered_url = final_url.casefold()
    if any(marker in lowered_url for marker in _CHALLENGE_URL_MARKERS):
        return "challenge_url"

    lowered_text = visible_text.casefold()
    for marker in _CHALLENGE_TEXT_MARKERS:
        if marker in lowered_text:
            return f"visible_text:{marker}"

    lowered_html = html.casefold()
    for marker in _CHALLENGE_HTML_MARKERS:
        if marker in lowered_html:
            return f"challenge_runtime:{marker}"
    return None


class ResumableImmoweltHeadedPropertySource(ImmoweltHeadedPropertySource):
    """Plain headed Immowelt acquisition with external challenge handoff and same-run resume.

    WohnWerk detects the challenge, checkpoints exact navigation state, and transfers control
    to an operator-provided handler. This class does not implement CAPTCHA/challenge solving.
    If the handler returns RESUME, the same run retries the same navigation point; it never
    silently restarts the shard from page one.
    """

    def __init__(
        self,
        *,
        request_delay_seconds: float = 15.0,
        incremental_pages: int = 2,
        hard_max_pages: int = 250,
        timeout_seconds: float = 45.0,
        challenge_handler: ChallengeHandler | None = None,
        storage_state_path: str | Path | None = None,
        challenge_retry_limit: int = 3,
        challenge_resume_backoff_seconds: float = 10.0,
    ) -> None:
        super().__init__(
            request_delay_seconds=request_delay_seconds,
            incremental_pages=incremental_pages,
            hard_max_pages=hard_max_pages,
            timeout_seconds=timeout_seconds,
        )
        self.challenge_handler = challenge_handler
        self.storage_state_path = (
            str(storage_state_path) if storage_state_path is not None else None
        )
        self.challenge_retry_limit = max(1, challenge_retry_limit)
        self.challenge_resume_backoff_seconds = max(1.0, challenge_resume_backoff_seconds)
        self._runtime_run_id: int | None = None
        self._runtime_shard_key: str | None = None
        self._checkpoint_callback: CheckpointCallback | None = None

    def bind_run_context(
        self,
        *,
        run_id: int,
        shard_key: str,
        checkpoint: CheckpointCallback,
    ) -> None:
        self._runtime_run_id = run_id
        self._runtime_shard_key = shard_key
        self._checkpoint_callback = checkpoint

    def clear_run_context(self) -> None:
        self._runtime_run_id = None
        self._runtime_shard_key = None
        self._checkpoint_callback = None

    async def _checkpoint(self, state: dict[str, Any]) -> None:
        callback = self._checkpoint_callback
        if callback is not None:
            await callback(state)

    async def _ensure_page(self) -> Page:
        if self._page is not None:
            return self._page

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=False,
            args=["--disable-crash-reporter"],
        )
        context_kwargs: dict[str, Any] = {"locale": "de-DE"}
        if self.storage_state_path and Path(self.storage_state_path).is_file():
            context_kwargs["storage_state"] = self.storage_state_path
        self._context = await self._browser.new_context(**context_kwargs)

        async def block_heavy_assets(route: Any) -> None:
            if route.request.resource_type in {"font", "image", "media"}:
                await route.abort()
            else:
                await route.continue_()

        await self._context.route("**/*", block_heavy_assets)
        self._page = await self._context.new_page()
        return self._page

    async def _navigation_snapshot(
        self,
        *,
        shard: SourceShardSpec,
        page_number: int,
        requested_url: str,
        final_url: str,
        phase: str,
        challenge_reason: str | None = None,
        challenge_attempt: int = 0,
    ) -> dict[str, Any]:
        region_key = str(shard.params.get("region_key") or "")
        price_band_key = str(shard.params.get("price_band_key") or "")
        region = REGIONS_BY_KEY.get(region_key)
        band = PRICE_BANDS_BY_KEY.get(price_band_key)
        return {
            "source": self.name,
            "run_id": self._runtime_run_id,
            "shard": self._runtime_shard_key or shard.key,
            "bundesland": region_key,
            "bundesland_location_id": (
                getattr(region, "immowelt_location_id", None) if region is not None else None
            ),
            "price_band": price_band_key,
            "price_min_eur": getattr(band, "minimum_eur", None) if band is not None else None,
            "price_max_eur": getattr(band, "maximum_eur", None) if band is not None else None,
            "page": page_number,
            "frontier_position": page_number,
            "requested_url": requested_url,
            "final_url": final_url,
            "phase": phase,
            "challenge_reason": challenge_reason,
            "challenge_attempt": challenge_attempt,
            "browser_storage_state": self.storage_state_path,
            "resume_navigation": "same_page",
        }

    async def _navigate_once(self, url: str) -> tuple[str, str, int | None, str]:
        if self._requests_made:
            await self._sleep()
        self._requests_made += 1
        page = await self._ensure_page()
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=int(self.timeout_seconds * 1000),
        )
        status = response.status if response is not None else None
        final_url = page.url
        html = await page.content()
        try:
            visible_text = await page.locator("body").inner_text(timeout=3000)
        except Exception:
            visible_text = ""
        return html, final_url, status, visible_text

    async def _load_page_with_handoff(
        self,
        *,
        shard: SourceShardSpec,
        page_number: int,
        url: str,
    ) -> tuple[str, str]:
        challenge_attempt = 0
        while True:
            html, final_url, status, visible_text = await self._navigate_once(url)
            reason = classify_immowelt_challenge(
                http_status=status,
                final_url=final_url,
                visible_text=visible_text,
                html=html,
            )
            if reason is None:
                if status is None:
                    raise RuntimeError("Immowelt navigation returned no response")
                if status == 429:
                    raise SourceFetchError(
                        "Immowelt HTTP 429; source rate limit observed",
                        halt_source=True,
                    )
                if status >= 400:
                    raise RuntimeError(f"Immowelt HTTP {status}")
                host = (urlparse(final_url).hostname or "").casefold()
                if host not in {"immowelt.de", "www.immowelt.de"}:
                    raise RuntimeError(f"Immowelt redirected off-site: {final_url!r}")

                page = await self._ensure_page()
                await page.wait_for_selector("h1", timeout=int(self.timeout_seconds * 1000))
                try:
                    await page.wait_for_selector(
                        f'[data-testid="{CARD_TEST_ID}"]',
                        timeout=min(8000, int(self.timeout_seconds * 1000)),
                    )
                except PlaywrightTimeoutError:
                    pass
                await page.wait_for_timeout(500)
                _validate_search_state(url, final_url)
                if self._context is not None:
                    await persist_browser_state(self._context, self.storage_state_path)
                await self._checkpoint(
                    await self._navigation_snapshot(
                        shard=shard,
                        page_number=page_number,
                        requested_url=url,
                        final_url=final_url,
                        phase="page_loaded",
                    )
                )
                return html, final_url

            challenge_attempt += 1
            if self._context is None:
                raise RuntimeError("Immowelt browser context missing during challenge handoff")
            await persist_browser_state(self._context, self.storage_state_path)
            snapshot = await self._navigation_snapshot(
                shard=shard,
                page_number=page_number,
                requested_url=url,
                final_url=final_url,
                phase="awaiting_challenge_handler",
                challenge_reason=reason,
                challenge_attempt=challenge_attempt,
            )
            snapshot["http_status"] = status
            await self._checkpoint(snapshot)

            if self.challenge_handler is None:
                raise ImmoweltChallengeDeferred(
                    f"Immowelt challenge deferred at page {page_number}: {reason}"
                )
            if challenge_attempt > self.challenge_retry_limit:
                raise ImmoweltChallengeDeferred(
                    f"Immowelt challenge retry limit reached at page {page_number}: {reason}"
                )

            request = ChallengeRequest(
                source_name=self.name,
                run_id=self._runtime_run_id or 0,
                shard_key=self._runtime_shard_key or shard.key,
                bundesland_key=str(shard.params.get("region_key") or ""),
                price_band_key=str(shard.params.get("price_band_key") or ""),
                page_number=page_number,
                requested_url=url,
                final_url=final_url,
                reason=reason,
                http_status=status,
                storage_state_path=self.storage_state_path,
                attempt=challenge_attempt,
            )
            page = await self._ensure_page()
            result = await invoke_challenge_handler(
                self.challenge_handler,
                request,
                page=page,
                browser_context=self._context,
            )
            await persist_browser_state(self._context, self.storage_state_path)

            if result.action == ChallengeAction.DEFER:
                raise ImmoweltChallengeDeferred(
                    result.message or f"Immowelt challenge handler deferred page {page_number}"
                )
            if result.action == ChallengeAction.FAIL:
                raise SourceFetchError(
                    result.message or f"Immowelt challenge handler failed page {page_number}",
                    halt_source=True,
                )

            await self._checkpoint(
                await self._navigation_snapshot(
                    shard=shard,
                    page_number=page_number,
                    requested_url=url,
                    final_url=page.url,
                    phase="challenge_handler_resumed",
                    challenge_reason=reason,
                    challenge_attempt=challenge_attempt,
                )
            )
            await asyncio.sleep(
                self.challenge_resume_backoff_seconds * random.uniform(0.8, 1.25)
            )
            # Retry the exact same requested URL. The run, shard and accumulated items stay intact.

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        del cursor
        region_key = str(shard.params.get("region_key") or "")
        price_band_key = str(shard.params.get("price_band_key") or "")
        self._page_url(region_key, price_band_key, 1)

        items_by_id: dict[str, RawProperty] = {}
        pages_fetched = 0
        cards_seen = 0
        cards_parsed = 0
        cards_total = 0
        project_cards_skipped = 0
        blank_cards_skipped = 0
        source_reported_count: int | None = None
        latest_reported_count: int | None = None
        max_reported_count = 0
        max_page = 1
        result_cap_hit = False
        page_number = 1

        try:
            while True:
                page_url_requested = self._page_url(region_key, price_band_key, page_number)
                page_html, page_url = await self._load_page_with_handoff(
                    shard=shard,
                    page_number=page_number,
                    url=page_url_requested,
                )
                parsed = parse_immowelt_search_page(
                    page_html,
                    page_url=page_url,
                    region_key=region_key,
                    price_band_key=price_band_key,
                )

                if page_number == 1:
                    _validate_page(parsed, page_number=1, expected_minimum=0)
                    source_reported_count = parsed.source_reported_count
                    latest_reported_count = parsed.source_reported_count
                    max_reported_count = parsed.source_reported_count
                    max_page = parsed.max_page
                    result_cap_hit = max_page >= self.hard_max_pages
                else:
                    latest_reported_count = parsed.source_reported_count
                    max_reported_count = max(max_reported_count, parsed.source_reported_count)
                    max_page = max(
                        max_page,
                        parsed.max_page,
                        max(1, math.ceil(max_reported_count / PAGE_SIZE)),
                    )
                    result_cap_hit = result_cap_hit or max_page >= self.hard_max_pages

                target_pages = min(
                    max_page,
                    self.hard_max_pages,
                    max_page if reconciliation else self.incremental_pages,
                )
                minimum = 0 if page_number == target_pages else math.ceil(PAGE_SIZE * 0.75)
                if page_number > 1:
                    _validate_page(parsed, page_number=page_number, expected_minimum=minimum)

                items_by_id.update({item.source_listing_id: item for item in parsed.items})
                pages_fetched += 1
                cards_seen += parsed.cards_seen
                cards_parsed += parsed.cards_parsed
                cards_total += parsed.cards_total
                project_cards_skipped += parsed.project_cards_skipped
                blank_cards_skipped += parsed.blank_cards_skipped

                await self._checkpoint(
                    {
                        **await self._navigation_snapshot(
                            shard=shard,
                            page_number=page_number,
                            requested_url=page_url_requested,
                            final_url=page_url,
                            phase="page_parsed",
                        ),
                        "pages_fetched": pages_fetched,
                        "items_seen_in_memory": len(items_by_id),
                        "target_pages": target_pages,
                        "discovery_max_page": max_page,
                    }
                )

                if page_number >= target_pages:
                    break
                page_number += 1
        except Exception as exc:
            if isinstance(exc, SourceFetchError):
                exc.pages_fetched = pages_fetched
                exc.items_seen = len(items_by_id)
                exc.source_reported_count = source_reported_count
                exc.next_cursor = {
                    "country_code": "DE",
                    "resume_page": page_number,
                    "resume_region_key": region_key,
                    "resume_price_band_key": price_band_key,
                    "discovery_cards_seen": cards_seen,
                    "discovery_cards_parsed": cards_parsed,
                    "discovery_cards_total": cards_total,
                    "discovery_project_cards_skipped": project_cards_skipped,
                    "discovery_blank_cards_skipped": blank_cards_skipped,
                    "discovery_max_page": max_page,
                    "discovery_latest_reported_count": latest_reported_count,
                    "discovery_max_reported_count": max_reported_count,
                    "browser_storage_state": self.storage_state_path,
                }
                exc.partial_items = list(items_by_id.values())
                raise
            raise SourceFetchError(
                f"Immowelt shard failed: {type(exc).__name__}: {exc}",
                pages_fetched=pages_fetched,
                items_seen=len(items_by_id),
                source_reported_count=source_reported_count,
                next_cursor={
                    "country_code": "DE",
                    "resume_page": page_number,
                    "resume_region_key": region_key,
                    "resume_price_band_key": price_band_key,
                    "discovery_cards_seen": cards_seen,
                    "discovery_cards_parsed": cards_parsed,
                    "discovery_cards_total": cards_total,
                    "discovery_project_cards_skipped": project_cards_skipped,
                    "discovery_blank_cards_skipped": blank_cards_skipped,
                    "discovery_max_page": max_page,
                    "discovery_latest_reported_count": latest_reported_count,
                    "discovery_max_reported_count": max_reported_count,
                    "browser_storage_state": self.storage_state_path,
                },
                partial_items=list(items_by_id.values()),
            ) from exc

        benchmark_count = latest_reported_count or source_reported_count or 0
        count_tolerance = max(3, math.ceil(benchmark_count * 0.01))
        count_delta = len(items_by_id) - benchmark_count
        count_plausible = (
            count_delta == 0 if not benchmark_count else abs(count_delta) <= count_tolerance
        )
        coverage_complete = bool(
            reconciliation
            and not result_cap_hit
            and project_cards_skipped == 0
            and blank_cards_skipped == 0
            and pages_fetched == max_page
            and cards_seen == cards_parsed
            and count_plausible
        )
        return SourceBatch(
            items=list(items_by_id.values()),
            next_cursor={
                "newest_ids": list(items_by_id)[:100],
                "discovery_cards_seen": cards_seen,
                "discovery_cards_parsed": cards_parsed,
                "discovery_cards_total": cards_total,
                "discovery_project_cards_skipped": project_cards_skipped,
                "discovery_blank_cards_skipped": blank_cards_skipped,
                "discovery_max_page": max_page,
                "discovery_initial_reported_count": source_reported_count,
                "discovery_latest_reported_count": latest_reported_count,
                "discovery_max_reported_count": max_reported_count,
                "discovery_count_delta": count_delta,
                "discovery_count_tolerance": count_tolerance,
                "browser_storage_state": self.storage_state_path,
                "country_code": "DE",
            },
            source_reported_count=source_reported_count,
            coverage_complete=coverage_complete,
            result_cap_hit=result_cap_hit,
            pages_fetched=pages_fetched,
        )
