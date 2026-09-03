from __future__ import annotations

import asyncio
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

BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
SEARCH_PATH = "/pc/v4/jobs"
PUBLIC_FRONTEND_KEY = "jobboerse-jobsuche"

_DEFAULT_QUERIES: tuple[tuple[str, str], ...] = (
    ("maschinenbau", "Maschinenbau"),
    ("konstrukteur", "Konstrukteur"),
    ("cad-konstrukteur", "CAD Konstrukteur"),
    ("entwicklungsingenieur", "Entwicklungsingenieur"),
    ("technischer-projektleiter", "Technischer Projektleiter"),
)


@dataclass(frozen=True, slots=True)
class ArbeitsagenturQuery:
    key: str
    text: str


def _string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _postal(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text.isdigit() or len(text) > 5:
        return None
    text = text.zfill(5)
    return text if len(text) == 5 else None


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reported_count(payload: dict[str, Any]) -> int | None:
    value = payload.get("maxErgebnisse")
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def parse_arbeitsagentur_job(item: dict[str, Any], *, query: ArbeitsagenturQuery) -> RawJob | None:
    reference = _string(item.get("refnr")) or _string(item.get("referenznummer"))
    title = _string(item.get("titel")) or _string(item.get("stellenangebotsTitel"))
    if reference is None or title is None:
        return None

    work_location = item.get("arbeitsort")
    if not isinstance(work_location, dict):
        work_location = {}
    postal_code = _postal(work_location.get("plz"))
    city = _string(work_location.get("ort"))
    region = _string(work_location.get("region"))
    country = _string(work_location.get("land"))
    street = _string(work_location.get("strasse"))

    labels = []
    if street:
        labels.append(street)
    place = " ".join(value for value in (postal_code, city) if value)
    if place:
        labels.append(place)
    if region and region.casefold() != (city or "").casefold():
        labels.append(region)
    location_text = ", ".join(labels) or city or region or country

    coordinates = work_location.get("koordinaten")
    if not isinstance(coordinates, dict):
        coordinates = {}
    latitude = _float(coordinates.get("lat"))
    longitude = _float(coordinates.get("lon"))

    official_url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{reference}"
    external_url = _string(item.get("externeUrl"))
    occupation = _string(item.get("beruf"))

    return RawJob(
        source_listing_id=f"arbeitsagentur:{reference}",
        url=official_url,
        title=title,
        company=_string(item.get("arbeitgeber")),
        description=occupation if occupation and occupation.casefold() != title.casefold() else None,
        locations=(
            [
                RawJobLocation(
                    postal_code=postal_code,
                    city=city,
                    location_text=location_text,
                    remote=False,
                )
            ]
            if location_text or postal_code or city
            else []
        ),
        raw_payload={
            "wohnwerk_board": "Bundesagentur für Arbeit Jobsuche",
            "country_code": "DE",
            "reference_number": reference,
            "query": query.text,
            "occupation": occupation,
            "published_at": item.get("aktuelleVeroeffentlichungsdatum"),
            "entry_date": item.get("eintrittsdatum"),
            "modified_at": item.get("modifikationsTimestamp"),
            "external_url": external_url,
            "latitude": latitude,
            "longitude": longitude,
            "search_location": work_location,
            "source_attribution": "Bundesagentur für Arbeit Jobsuche",
            "description_truncated_by_source": True,
        },
    )


class ArbeitsagenturJobSource(JobSource):
    """Targeted German engineering frontier over the public BA Jobsuche web API.

    The endpoint is used by the official Jobsuche frontend and is not an official
    developer API.  The adapter therefore remains deliberately coverage-incomplete
    and must never deactivate listings merely because they disappear from a shard.
    """

    name = "arbeitsagentur-jobsuche-de"

    def __init__(
        self,
        *,
        queries: list[ArbeitsagenturQuery] | None = None,
        page_size: int = 100,
        max_pages: int = 5,
        max_days_old: int = 30,
        request_delay_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if page_size <= 0 or max_pages <= 0 or max_days_old <= 0:
            raise ValueError("page_size, max_pages and max_days_old must be positive")
        self.queries = queries or [ArbeitsagenturQuery(*value) for value in _DEFAULT_QUERIES]
        self.page_size = min(page_size, 100)
        self.max_pages = max_pages
        self.max_days_old = min(max_days_old, 100)
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.transport = transport
        self._seen_ids: set[str] = set()

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=query.key,
                params={"query": query.text},
                result_cap=self.page_size * self.max_pages,
            )
            for query in self.queries
        ]

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawJob]:
        del cursor, reconciliation
        query_text = shard.params.get("query")
        if not isinstance(query_text, str) or not query_text.strip():
            raise TypeError(f"Invalid Arbeitsagentur shard params: {shard.params!r}")
        query = ArbeitsagenturQuery(shard.key, query_text.strip())

        items: list[RawJob] = []
        pages_fetched = 0
        source_reported_count: int | None = None
        raw_seen = 0
        malformed = 0
        duplicates = 0
        exhausted = False

        headers = {
            "Accept": "application/json",
            "X-API-Key": PUBLIC_FRONTEND_KEY,
            "User-Agent": "WohnWerk/DE-job-research",
        }
        async with httpx.AsyncClient(
            base_url=BASE_URL,
            headers=headers,
            timeout=60.0,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            for page in range(1, self.max_pages + 1):
                if pages_fetched and self.request_delay_seconds:
                    await asyncio.sleep(self.request_delay_seconds)
                params = {
                    "angebotsart": 1,
                    "was": query.text,
                    "page": page,
                    "size": self.page_size,
                    "veroeffentlichtseit": self.max_days_old,
                }
                try:
                    response = await client.get(SEARCH_PATH, params=params)
                    response.raise_for_status()
                    payload = response.json()
                except (httpx.HTTPError, ValueError) as exc:
                    raise SourceFetchError(
                        f"Arbeitsagentur failure for {shard.key} page {page}: {type(exc).__name__}",
                        pages_fetched=pages_fetched,
                        items_seen=len(items),
                        source_reported_count=source_reported_count,
                        partial_items=items,
                        next_cursor={
                            "country_code": "DE",
                            "query": query.text,
                            "last_page": pages_fetched,
                            "coverage": "targeted-incomplete",
                        },
                    ) from exc
                if not isinstance(payload, dict):
                    raise SourceFetchError(
                        f"Arbeitsagentur returned an invalid payload for {shard.key} page {page}",
                        pages_fetched=pages_fetched,
                        partial_items=items,
                    )

                pages_fetched += 1
                reported = _reported_count(payload)
                if reported is not None:
                    source_reported_count = max(source_reported_count or 0, reported)
                raw_results = payload.get("stellenangebote")
                if not isinstance(raw_results, list):
                    raise SourceFetchError(
                        f"Arbeitsagentur payload has no stellenangebote list for {shard.key}",
                        pages_fetched=pages_fetched,
                        partial_items=items,
                    )

                raw_seen += len(raw_results)
                for raw in raw_results:
                    if not isinstance(raw, dict):
                        malformed += 1
                        continue
                    item = parse_arbeitsagentur_job(raw, query=query)
                    if item is None:
                        malformed += 1
                        continue
                    if item.source_listing_id in self._seen_ids:
                        duplicates += 1
                        continue
                    self._seen_ids.add(item.source_listing_id)
                    items.append(item)

                if len(raw_results) < self.page_size:
                    exhausted = True
                    break

        cap_hit = not exhausted and pages_fetched >= self.max_pages
        return SourceBatch(
            items=items,
            next_cursor={
                "strategy": "ba-public-web-api-title-frontier",
                "country_code": "DE",
                "query": query.text,
                "raw_results_seen": raw_seen,
                "deduped_items": len(items),
                "cross_query_duplicates": duplicates,
                "malformed_results": malformed,
                "max_days_old": self.max_days_old,
                "page_size": self.page_size,
                "max_pages": self.max_pages,
                "source_attribution": "Bundesagentur für Arbeit Jobsuche",
                "coverage": "targeted-incomplete",
            },
            source_reported_count=source_reported_count,
            coverage_complete=False,
            result_cap_hit=cap_hit,
            pages_fetched=pages_fetched,
        )
