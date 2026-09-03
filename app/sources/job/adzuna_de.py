from __future__ import annotations

import re
from typing import Any

import httpx

from app.sources.base import RawJob, SourceBatch, SourceFetchError, SourceShardSpec
from app.sources.job.adzuna import BASE_URL, AdzunaJobSource, AdzunaQuery, parse_adzuna_job

_POSTAL_CITY_RE = re.compile(r"^(?P<postal>\d{5})\s+(?P<city>.+)$")
_GERMANY_LABELS = {"de", "deutschland", "germany"}


def _normalize_german_location(item: RawJob) -> RawJob:
    for location in item.locations:
        text = (location.location_text or "").strip()
        first = text.split(",", 1)[0].strip()
        match = _POSTAL_CITY_RE.match(first)
        if match:
            location.postal_code = match.group("postal")
            location.city = match.group("city").strip() or None
        elif (location.city or "").strip().casefold() in _GERMANY_LABELS:
            location.city = None
    item.raw_payload["country_code"] = "DE"
    return item


class AdzunaGermanyJobSource(AdzunaJobSource):
    """Germany engineering frontier using Adzuna's documented country=de API."""

    name = "adzuna-api-de"

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawJob]:
        del cursor, reconciliation
        title_query = shard.params.get("title_query")
        if not isinstance(title_query, str) or not title_query.strip():
            raise TypeError(f"Invalid Adzuna shard params: {shard.params!r}")
        query = AdzunaQuery(shard.key, title_query.strip())

        params = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": self.results_per_query,
            "title_only": query.title_query,
            "max_days_old": self.max_days_old,
            "sort_by": "date",
            "sort_dir": "down",
            "content-type": "application/json",
        }
        url = f"{BASE_URL}/jobs/de/search/1"

        await self._rate_limit()
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                transport=self.transport,
                headers={"Accept": "application/json"},
            ) as client:
                response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise SourceFetchError(
                f"Adzuna DE API transport failure for {shard.key}: {type(exc).__name__}",
                pages_fetched=0,
            ) from exc

        if response.status_code != 200:
            raise SourceFetchError(
                f"Adzuna DE API returned HTTP {response.status_code} for {shard.key}",
                pages_fetched=1,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceFetchError(
                f"Adzuna DE API returned invalid JSON for {shard.key}",
                pages_fetched=1,
            ) from exc
        if not isinstance(payload, dict):
            raise SourceFetchError(
                f"Adzuna DE API returned an invalid payload for {shard.key}",
                pages_fetched=1,
            )

        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise SourceFetchError(
                f"Adzuna DE API payload has no results list for {shard.key}",
                pages_fetched=1,
            )

        items: list[RawJob] = []
        duplicates = 0
        malformed = 0
        for raw in raw_results:
            if not isinstance(raw, dict):
                malformed += 1
                continue
            item = parse_adzuna_job(raw, query=query)
            if item is None:
                malformed += 1
                continue
            item = _normalize_german_location(item)
            if item.source_listing_id in self._seen_ids:
                duplicates += 1
                continue
            self._seen_ids.add(item.source_listing_id)
            items.append(item)

        reported = payload.get("count")
        source_reported_count = reported if isinstance(reported, int) and reported >= 0 else None
        return SourceBatch(
            items=items,
            next_cursor={
                "strategy": "official-api-first-page-title-frontier",
                "country_code": "DE",
                "title_query": query.title_query,
                "api_results": len(raw_results),
                "deduped_items": len(items),
                "cross_query_duplicates": duplicates,
                "malformed_results": malformed,
                "results_per_query": self.results_per_query,
                "max_days_old": self.max_days_old,
                "source_attribution": "Adzuna API",
            },
            source_reported_count=source_reported_count,
            coverage_complete=False,
            result_cap_hit=False,
            pages_fetched=1,
        )
