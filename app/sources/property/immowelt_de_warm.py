from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.sources.property.germany import GERMAN_REGIONS
from app.sources.property.immowelt_de import (
    BASE_URL,
    ImmoweltGermanyPropertySource,
)


class ImmoweltWarmSessionPropertySource(ImmoweltGermanyPropertySource):
    """Immowelt adapter that enters through the public SEO SERP once per browser context.

    The live frontend transitions from the public SEO result page to
    ``/classified-search`` when filters or sorting are changed.  A cold direct
    navigation to ``/classified-search`` can be rejected while that normal
    browser path succeeds, so preserve the frontend navigation shape without
    changing any parser, retention or coverage semantics.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._search_context_primed = False

    @staticmethod
    def _warmup_url(requested_url: str) -> str:
        query = parse_qs(urlparse(requested_url).query)
        locations = query.get("locations") or []
        if len(locations) != 1:
            raise ValueError(
                "Immowelt classified search requires exactly one location before warm-up"
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
            raise ValueError(f"Unknown Immowelt location id for warm-up: {location_id!r}")

        return (
            f"{BASE_URL}/suche/kaufen/haus/{region.key}/"
            f"{region.immowelt_location_id.casefold()}"
        )

    async def _prime_search_context(self, requested_url: str) -> None:
        if self._search_context_primed:
            return

        page = await self._ensure_page()
        warmup_url = self._warmup_url(requested_url)
        response = await page.goto(
            warmup_url,
            wait_until="domcontentloaded",
            timeout=int(self.timeout_seconds * 1000),
        )
        if response is None:
            raise RuntimeError("Immowelt warm-up navigation returned no response")
        if response.status >= 400:
            raise RuntimeError(f"Immowelt warm-up HTTP {response.status}")

        host = (urlparse(page.url).hostname or "").casefold()
        if host not in {"immowelt.de", "www.immowelt.de"}:
            raise RuntimeError(f"Immowelt warm-up redirected off-site: {page.url!r}")

        await page.wait_for_selector("h1", timeout=int(self.timeout_seconds * 1000))
        await page.wait_for_timeout(350)

        self._search_context_primed = True
        # Count the warm-up as a navigation so the normal low-rate delay applies
        # before the first classified-search request as well.
        self._requests_made += 1

    async def _load_html(self, url: str) -> tuple[str, str]:
        await self._prime_search_context(url)
        return await super()._load_html(url)
