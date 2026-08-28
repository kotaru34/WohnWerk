from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.sources.base import (
    JobSource,
    RawJob,
    RawJobLocation,
    SourceBatch,
    SourceFetchError,
    SourceShardSpec,
)

BASE_URL = "https://at.jooble.org"
_POSTAL_CITY_RE = re.compile(r"^(?P<postal>\d{4})\s+(?P<city>.+)$")

_DEFAULT_QUERIES: tuple[tuple[str, str], ...] = (
    ("maschinenbau", "Maschinenbau"),
    ("konstrukteur", "Konstrukteur"),
    ("cad-konstrukteur", "CAD Konstrukteur"),
    ("entwicklungsingenieur", "Entwicklungsingenieur"),
    ("technischer-projektleiter", "Technischer Projektleiter"),
)


@dataclass(frozen=True, slots=True)
class JoobleQuery:
    key: str
    keywords: str


def _string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _location(value: Any) -> RawJobLocation | None:
    location_text = _string(value)
    if location_text is None:
        return None

    first = location_text.split(",", 1)[0].strip()
    match = _POSTAL_CITY_RE.match(first)
    if match:
        postal_code = match.group("postal")
        city = match.group("city").strip() or None
    else:
        postal_code = None
        city = None if first.casefold() in {"österreich", "austria", "at"} else first

    return RawJobLocation(
        postal_code=postal_code,
        city=city,
        location_text=location_text,
        remote=False,
    )


def parse_jooble_job(item: dict[str, Any], *, query: JoobleQuery) -> RawJob | None:
    raw_id = item.get("id")
    source_id = _string(raw_id) if isinstance(raw_id, str) else (
        str(raw_id) if raw_id is not None else None
    )
    title = _string(item.get("title"))
    link = _string(item.get("link"))
    if source_id is None or title is None or link is None:
        return None

    source_name = _string(item.get("source"))
    salary_text = _string(item.get("salary"))
    location = _location(item.get("location"))

    return RawJob(
        source_listing_id=f"jooble:{source_id}",
        url=link,
        title=title,
        company=_string(item.get("company")),
        # Jooble explicitly documents this as a search-result snippet, not the
        # complete vacancy body. Keep that provenance and do no advertiser crawl.
        description=_string(item.get("snippet")),
        salary_text=salary_text,
        locations=[location] if location is not None else [],
        raw_payload={
            "wohnwerk_board": "Jooble REST API",
            "jooble_id": source_id,
            "jooble_query": query.keywords,
            "jooble_source": source_name,
            "employment_type": item.get("type"),
            "updated": item.get("updated"),
            "description_truncated_by_source": True,
            "source_attribution": "Jooble REST API",
        },
    )


class JoobleJobSource(JobSource):
    """Austria job frontier using Jooble's documented regional REST API."""

    name = "jooble-api-at"

    def __init__(
        self,
        *,
        api_key: str,
        queries: list[JoobleQuery] | None = None,
        results_per_query: int = 50,
        request_delay_seconds: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Jooble Austria API key is required")
        self.api_key = api_key.strip()
        self.queries = queries or [JoobleQuery(*row) for row in _DEFAULT_QUERIES]
        self.results_per_query = max(1, min(results_per_query, 50))
        self.request_delay_seconds = max(1.0, request_delay_seconds)
        self.transport = transport
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._seen_ids: set[str] = set()

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=query.key,
                params={"keywords": query.keywords},
                priority=index,
            )
            for index, query in enumerate(self.queries)
        ]

    async def _rate_limit(self) -> None:
        async with self._request_lock:
            remaining = self.request_delay_seconds - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_request_at = time.monotonic()

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawJob]:
        del cursor, reconciliation
        keywords = shard.params.get("keywords")
        if not isinstance(keywords, str) or not keywords.strip():
            raise TypeError(f"Invalid Jooble shard params: {shard.params!r}")
        query = JoobleQuery(shard.key, keywords.strip())

        # The regional API key is part of the path. Never expose this URL in
        # diagnostics or exceptions.
        url = f"{BASE_URL}/api/{self.api_key}"
        payload = {
            "keywords": query.keywords,
            "location": "Österreich",
            "page": "1",
            "ResultOnPage": self.results_per_query,
            "SearchMode": 0,
            "companysearch": False,
        }

        await self._rate_limit()
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                transport=self.transport,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            ) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise SourceFetchError(
                f"Jooble API transport failure for {shard.key}: {type(exc).__name__}",
                pages_fetched=0,
            ) from exc

        if response.status_code != 200:
            raise SourceFetchError(
                f"Jooble API returned HTTP {response.status_code} for {shard.key}",
                pages_fetched=1,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise SourceFetchError(
                f"Jooble API returned invalid JSON for {shard.key}",
                pages_fetched=1,
            ) from exc
        if not isinstance(data, dict):
            raise SourceFetchError(
                f"Jooble API returned an invalid payload for {shard.key}",
                pages_fetched=1,
            )

        raw_jobs = data.get("jobs")
        if not isinstance(raw_jobs, list):
            raise SourceFetchError(
                f"Jooble API payload has no jobs list for {shard.key}",
                pages_fetched=1,
            )

        items: list[RawJob] = []
        duplicates = 0
        malformed = 0
        for raw in raw_jobs:
            if not isinstance(raw, dict):
                malformed += 1
                continue
            item = parse_jooble_job(raw, query=query)
            if item is None:
                malformed += 1
                continue
            if item.source_listing_id in self._seen_ids:
                duplicates += 1
                continue
            self._seen_ids.add(item.source_listing_id)
            items.append(item)

        reported = data.get("totalCount")
        source_reported_count = reported if isinstance(reported, int) and reported >= 0 else None
        return SourceBatch(
            items=items,
            next_cursor={
                "strategy": "official-api-first-page-keyword-frontier",
                "keywords": query.keywords,
                "api_results": len(raw_jobs),
                "deduped_items": len(items),
                "cross_query_duplicates": duplicates,
                "malformed_results": malformed,
                "results_per_query": self.results_per_query,
                "source_attribution": "Jooble REST API",
                "quota_note": "free key documented as 500 lifetime requests",
            },
            source_reported_count=source_reported_count,
            coverage_complete=False,
            result_cap_hit=False,
            pages_fetched=1,
        )
