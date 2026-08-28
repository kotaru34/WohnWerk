from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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

BASE_URL = "https://api.adzuna.com/v1/api"
COUNTRY = "at"
_POSTAL_CITY_RE = re.compile(r"^(?P<postal>\d{4})\s+(?P<city>.+)$")

_DEFAULT_QUERIES: tuple[tuple[str, str], ...] = (
    ("maschinenbau", "Maschinenbau"),
    ("konstrukteur", "Konstrukteur"),
    ("cad-konstrukteur", "CAD Konstrukteur"),
    ("entwicklungsingenieur", "Entwicklungsingenieur"),
    ("technischer-projektleiter", "Technischer Projektleiter"),
)


@dataclass(frozen=True, slots=True)
class AdzunaQuery:
    key: str
    title_query: str


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _company(item: dict[str, Any]) -> str | None:
    value = item.get("company")
    if isinstance(value, dict):
        return _string(value.get("display_name")) or _string(value.get("canonical_name"))
    return None


def _location(item: dict[str, Any]) -> RawJobLocation | None:
    value = item.get("location")
    if not isinstance(value, dict):
        return None

    display_name = _string(value.get("display_name"))
    area = value.get("area")
    area_parts = (
        [part.strip() for part in area if isinstance(part, str) and part.strip()]
        if isinstance(area, list)
        else []
    )

    location_text = display_name or (", ".join(area_parts) if area_parts else None)
    if location_text is None:
        return None

    postal_code: str | None = None
    city: str | None = None
    first = location_text.split(",", 1)[0].strip()
    match = _POSTAL_CITY_RE.match(first)
    if match:
        postal_code = match.group("postal")
        city = match.group("city").strip() or None
    elif first.casefold() not in {"austria", "österreich", "at"}:
        city = first
    elif area_parts:
        for part in reversed(area_parts):
            if part.casefold() not in {"austria", "österreich", "at"}:
                city = part
                break

    return RawJobLocation(
        postal_code=postal_code,
        city=city,
        location_text=location_text,
        remote=False,
    )


def parse_adzuna_job(item: dict[str, Any], *, query: AdzunaQuery) -> RawJob | None:
    source_id = _string(item.get("id")) or (
        str(item["id"]) if item.get("id") is not None else None
    )
    title = _string(item.get("title"))
    redirect_url = _string(item.get("redirect_url"))
    if source_id is None or title is None or redirect_url is None:
        return None

    salary_min = _decimal(item.get("salary_min"))
    salary_max = _decimal(item.get("salary_max"))
    salary_predicted = str(item.get("salary_is_predicted") or "0") == "1"
    salary_present = salary_min is not None or salary_max is not None
    location = _location(item)

    raw_payload: dict[str, Any] = {
        "wohnwerk_board": "Adzuna API",
        "adzuna_id": source_id,
        "adzuna_query": query.title_query,
        "created": item.get("created"),
        "category": item.get("category"),
        "contract_time": item.get("contract_time"),
        "contract_type": item.get("contract_type"),
        "salary_is_predicted": salary_predicted,
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "description_truncated_by_source": True,
        "source_attribution": "Adzuna API",
    }

    salary_provenance = None
    salary_confidence = None
    if salary_present:
        salary_provenance = "ESTIMATED" if salary_predicted else "EXPLICIT"
        salary_confidence = Decimal("0.500") if salary_predicted else Decimal("0.900")

    return RawJob(
        source_listing_id=f"adzuna:{source_id}",
        url=redirect_url,
        title=title,
        company=_company(item),
        description=_string(item.get("description")),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency="EUR" if salary_present else None,
        # Adzuna documents salary values in local currency but does not expose a
        # reliable period on the search object. Preserve the amount without
        # inventing annual/monthly semantics.
        salary_period=None,
        salary_payment_count=None,
        salary_provenance=salary_provenance,
        salary_confidence=salary_confidence,
        salary_is_minimum_only=True if salary_min is not None and salary_max is None else None,
        locations=[location] if location is not None else [],
        raw_payload=raw_payload,
    )


class AdzunaJobSource(JobSource):
    """Low-request Austria job frontier using Adzuna's documented public API."""

    name = "adzuna-api-at"

    def __init__(
        self,
        *,
        app_id: str,
        app_key: str,
        queries: list[AdzunaQuery] | None = None,
        results_per_query: int = 50,
        max_days_old: int = 30,
        request_delay_seconds: float = 2.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not app_id.strip() or not app_key.strip():
            raise ValueError("Adzuna API credentials are required")
        self.app_id = app_id.strip()
        self.app_key = app_key.strip()
        self.queries = queries or [AdzunaQuery(*row) for row in _DEFAULT_QUERIES]
        self.results_per_query = max(1, min(results_per_query, 50))
        self.max_days_old = max(1, max_days_old)
        self.request_delay_seconds = max(2.5, request_delay_seconds)
        self.transport = transport
        self._last_request_at = 0.0
        self._request_lock = asyncio.Lock()
        self._seen_ids: set[str] = set()

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=query.key,
                params={"title_query": query.title_query},
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
        url = f"{BASE_URL}/jobs/{COUNTRY}/search/1"

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
                f"Adzuna API transport failure for {shard.key}: {type(exc).__name__}",
                pages_fetched=0,
            ) from exc

        # Never include response.request.url here: it contains the API key.
        if response.status_code != 200:
            raise SourceFetchError(
                f"Adzuna API returned HTTP {response.status_code} for {shard.key}",
                pages_fetched=1,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceFetchError(
                f"Adzuna API returned invalid JSON for {shard.key}",
                pages_fetched=1,
            ) from exc
        if not isinstance(payload, dict):
            raise SourceFetchError(
                f"Adzuna API returned an invalid payload for {shard.key}",
                pages_fetched=1,
            )

        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise SourceFetchError(
                f"Adzuna API payload has no results list for {shard.key}",
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
            if item.source_listing_id in self._seen_ids:
                duplicates += 1
                continue
            self._seen_ids.add(item.source_listing_id)
            items.append(item)

        reported = payload.get("count")
        source_reported_count = (
            reported if isinstance(reported, int) and reported >= 0 else None
        )
        return SourceBatch(
            items=items,
            next_cursor={
                "strategy": "official-api-first-page-title-frontier",
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
