from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.sources.property.germany import GERMAN_REGIONS
from app.sources.property.immowelt_de import (
    BASE_URL,
    CARD_TEST_ID,
    ImmoweltGermanyPropertySource,
    _validate_search_state,
)

_PRICE_BUTTON = 'button[data-testid="search-mfe-filtersbar-price-range-button"]'
_PRICE_MIN_INPUT = '[data-testid="searchmfe-textfield-testid-price-min"] input'
_PRICE_MAX_INPUT = '[data-testid="searchmfe-textfield-testid-price-max"] input'
_PRICE_SUBMIT = 'button[data-testid="search-mfe-modal-submit-button"]'
_SORT_BUTTON = 'button[data-testid="core-sort-testid"]'


class ImmoweltWarmSessionPropertySource(ImmoweltGermanyPropertySource):
    """Immowelt adapter that drives the public search UI in ordinary Chromium.

    The live frontend accepts the public SEO SERP and transitions to
    ``/classified-search`` when its price, sort and pagination controls are used,
    while a direct cold or warm ``page.goto('/classified-search?...')`` can be
    rejected.  This adapter therefore never navigates directly to the runtime
    search route.  It establishes the same state through the public controls and
    then reuses the deterministic parser, retention and coverage logic from the
    base adapter.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._active_search_key: tuple[str, str, str, str, str, str] | None = None
        self._active_page = 0

    @staticmethod
    def _query(requested_url: str) -> dict[str, list[str]]:
        parsed = urlparse(requested_url)
        if parsed.path != "/classified-search":
            raise ValueError(f"Unexpected Immowelt search URL: {requested_url!r}")
        return parse_qs(parsed.query)

    @classmethod
    def _search_key(cls, requested_url: str) -> tuple[str, str, str, str, str, str]:
        query = cls._query(requested_url)
        required = (
            "distributionTypes",
            "estateTypes",
            "locations",
            "priceMin",
            "priceMax",
            "order",
        )
        values: list[str] = []
        for key in required:
            parts = query.get(key) or []
            if len(parts) != 1:
                raise ValueError(f"Immowelt search requires exactly one {key}: {requested_url!r}")
            values.append(parts[0])
        return tuple(values)  # type: ignore[return-value]

    @classmethod
    def _requested_page(cls, requested_url: str) -> int:
        parts = cls._query(requested_url).get("page") or ["1"]
        if len(parts) != 1 or not parts[0].isdigit():
            raise ValueError(f"Invalid Immowelt page state: {requested_url!r}")
        page = int(parts[0])
        if page <= 0:
            raise ValueError(f"Invalid Immowelt page state: {requested_url!r}")
        return page

    @classmethod
    def _with_page(cls, requested_url: str, page: int) -> str:
        parsed = urlparse(requested_url)
        query = cls._query(requested_url)
        flat = {key: values[0] for key, values in query.items() if values}
        flat["page"] = str(page)
        return urlunparse(parsed._replace(query=urlencode(flat)))

    @staticmethod
    def _warmup_url(requested_url: str) -> str:
        query = parse_qs(urlparse(requested_url).query)
        locations = query.get("locations") or []
        if len(locations) != 1:
            raise ValueError(
                "Immowelt classified search requires exactly one location before UI entry"
            )

        location_id = locations[0]
        region = next(
            (
                candidate
                for candidate in GERMAN_REGIONS
                if candidate.immowelt_location_id.casefold() == location_id.casefold()
            ),
            None,
        )
        if region is None:
            raise ValueError(f"Unknown Immowelt location id for UI entry: {location_id!r}")

        return (
            f"{BASE_URL}/suche/kaufen/haus/{region.key}/"
            f"{region.immowelt_location_id.casefold()}"
        )

    async def _assert_public_page(self) -> None:
        page = await self._ensure_page()
        host = (urlparse(page.url).hostname or "").casefold()
        if host not in {"immowelt.de", "www.immowelt.de"}:
            raise RuntimeError(f"Immowelt redirected off-site: {page.url!r}")

        html = await page.content()
        lowered = html.casefold()
        if (
            "captcha" in lowered
            or "access denied" in lowered
            or "ich bin kein roboter" in lowered
        ):
            raise RuntimeError("Immowelt presented an access challenge; crawler stopped")

    async def _wait_serp(self) -> None:
        page = await self._ensure_page()
        await page.wait_for_selector("h1", timeout=int(self.timeout_seconds * 1000))
        try:
            await page.wait_for_selector(
                f'[data-testid="{CARD_TEST_ID}"]',
                timeout=min(8000, int(self.timeout_seconds * 1000)),
            )
        except PlaywrightTimeoutError:
            # Empty filtered result sets legitimately have no cards.  The parser
            # remains authoritative after the heading has rendered.
            pass
        await page.wait_for_timeout(500)
        await self._assert_public_page()

    async def _wait_query_subset(self, expected: dict[str, str]) -> None:
        page = await self._ensure_page()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_seconds
        last_url = page.url

        while loop.time() < deadline:
            last_url = page.url
            parsed = urlparse(last_url)
            actual = parse_qs(parsed.query)
            if parsed.path == "/classified-search" and all(
                actual.get(key) == [value] for key, value in expected.items()
            ):
                return
            await page.wait_for_timeout(200)

        raise RuntimeError(
            f"Immowelt UI search state did not settle: expected {expected!r}, "
            f"last URL {last_url!r}"
        )

    async def _enter_region_serp(self, requested_url: str) -> None:
        page = await self._ensure_page()
        warmup_url = self._warmup_url(requested_url)
        response = await page.goto(
            warmup_url,
            wait_until="domcontentloaded",
            timeout=int(self.timeout_seconds * 1000),
        )
        if response is None:
            raise RuntimeError("Immowelt SEO navigation returned no response")
        if response.status >= 400:
            raise RuntimeError(f"Immowelt SEO navigation HTTP {response.status}")
        await self._wait_serp()

    async def _apply_price(self, requested_url: str) -> None:
        page = await self._ensure_page()
        query = self._query(requested_url)
        price_min = (query.get("priceMin") or [""])[0]
        price_max = (query.get("priceMax") or [""])[0]

        await page.locator(_PRICE_BUTTON).wait_for(
            state="visible", timeout=int(self.timeout_seconds * 1000)
        )
        await page.locator(_PRICE_BUTTON).click(timeout=int(self.timeout_seconds * 1000))

        minimum = page.locator(_PRICE_MIN_INPUT)
        maximum = page.locator(_PRICE_MAX_INPUT)
        await minimum.wait_for(state="visible", timeout=int(self.timeout_seconds * 1000))
        await maximum.wait_for(state="visible", timeout=int(self.timeout_seconds * 1000))
        await minimum.fill(price_min)
        await maximum.fill(price_max)

        submit = page.locator(_PRICE_SUBMIT)
        await submit.wait_for(state="visible", timeout=int(self.timeout_seconds * 1000))
        await submit.click(timeout=int(self.timeout_seconds * 1000))

        await self._wait_query_subset(
            {
                "distributionTypes": (query.get("distributionTypes") or [""])[0],
                "estateTypes": (query.get("estateTypes") or [""])[0],
                "locations": (query.get("locations") or [""])[0],
                "priceMin": price_min,
                "priceMax": price_max,
            }
        )
        await self._wait_serp()

    async def _apply_sort(self, requested_url: str) -> None:
        page = await self._ensure_page()
        query = self._query(requested_url)

        sort_button = page.locator(_SORT_BUTTON)
        await sort_button.wait_for(state="visible", timeout=int(self.timeout_seconds * 1000))
        await sort_button.click(timeout=int(self.timeout_seconds * 1000))

        newest = page.get_by_role("menuitem", name="Aktuellste Angebote", exact=True).first
        await newest.wait_for(state="visible", timeout=int(self.timeout_seconds * 1000))
        await newest.click(timeout=int(self.timeout_seconds * 1000))

        await self._wait_query_subset(
            {
                "locations": (query.get("locations") or [""])[0],
                "priceMin": (query.get("priceMin") or [""])[0],
                "priceMax": (query.get("priceMax") or [""])[0],
                "order": (query.get("order") or [""])[0],
            }
        )
        await self._wait_serp()

    async def _establish_page_one(self, requested_url: str) -> None:
        page_one_url = self._with_page(requested_url, 1)
        await self._enter_region_serp(page_one_url)
        await self._apply_price(page_one_url)
        await self._apply_sort(page_one_url)

        page = await self._ensure_page()
        _validate_search_state(page_one_url, page.url)
        self._active_search_key = self._search_key(page_one_url)
        self._active_page = 1

    async def _advance_to_page(self, requested_url: str, target_page: int) -> None:
        page = await self._ensure_page()
        while self._active_page < target_page:
            next_page = self._active_page + 1
            button = page.locator(f'button[aria-label="zu seite {next_page}"]')
            await button.wait_for(state="visible", timeout=int(self.timeout_seconds * 1000))
            await button.click(timeout=int(self.timeout_seconds * 1000))

            expected_url = self._with_page(requested_url, next_page)
            query = self._query(expected_url)
            await self._wait_query_subset(
                {
                    "locations": (query.get("locations") or [""])[0],
                    "priceMin": (query.get("priceMin") or [""])[0],
                    "priceMax": (query.get("priceMax") or [""])[0],
                    "order": (query.get("order") or [""])[0],
                    "page": str(next_page),
                }
            )
            await self._wait_serp()
            _validate_search_state(expected_url, page.url)
            self._active_page = next_page

    async def _load_html(self, url: str) -> tuple[str, str]:
        if self._requests_made:
            await self._sleep()

        desired_key = self._search_key(url)
        desired_page = self._requested_page(url)

        if self._active_search_key != desired_key or desired_page <= self._active_page:
            await self._establish_page_one(url)

        if desired_page > self._active_page:
            await self._advance_to_page(url, desired_page)

        page = await self._ensure_page()
        _validate_search_state(url, page.url)
        await self._assert_public_page()

        self._requests_made += 1
        return await page.content(), page.url
