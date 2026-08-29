from __future__ import annotations

import asyncio
import html
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from app.sources.base import (
    JobSource,
    RawJob,
    RawJobLocation,
    SourceBatch,
    SourceFetchError,
    SourceShardSpec,
)

BASE_URL = "https://www.willhaben.at"

_JOB_PATH_RE = re.compile(
    r"(?:https?://(?:www\.)?willhaben\.at)?"
    r"(?P<path>/jobs/job/[^\"'?#]+/(?P<id>\d+))(?:[/?#]|$)"
)
_RESULT_COUNT_RE = re.compile(
    r"(?<!\d)(?P<count>\d{1,3}(?:\.\d{3})*|\d+)\s+"
    r"(?:Anzeigen\b|Jobs\s+für\b)",
    re.IGNORECASE,
)
_META_RE = re.compile(r"^(?P<date>\d{2}\.\d{2}\.)\s*\|\s*(?P<rest>.+)$")
_POSTAL_CITY_RE = re.compile(r"^(?P<postal>\d{4})\s+(?P<city>.+)$")
_DETAIL_WORTHY_RE = re.compile(
    r"(?:konstruk|maschinenbau|mechanical|cad|entwicklungsingenieur|"
    r"development\s+engineer|design\s+engineer|project\s+engineer|projektingenieur|"
    r"technisch\w*\s+projekt|projektleiter|sondermaschinen|fahrzeug|automotive|"
    r"berechnungsingenieur|simulation\s+engineer|product\s+engineer|"
    r"mechanik|baugruppen|antrieb|chassis)",
    re.IGNORECASE,
)
_SALARY_DETAIL_CUE_RE = re.compile(
    r"(?:brutto(?:monats|jahres)?gehalt|mindestgehalt|mindestentgelt|\bgehalt\b|salary)",
    re.IGNORECASE,
)
_SALARY_DETAIL_VALUE_RE = re.compile(
    r"(?:€|\bEUR\b).{0,60}(?:monatlich|jährlich|jaehrlich|pro\s+monat|pro\s+jahr|"
    r"/\s*monat|/\s*jahr|p\.?\s*a\.?)|"
    r"(?:monatlich|jährlich|jaehrlich|pro\s+monat|pro\s+jahr).{0,60}(?:€|\bEUR\b)",
    re.IGNORECASE,
)

_EMPLOYMENT_TOKENS = {
    "vollzeit",
    "teilzeit",
    "freiberuflich",
    "geringfügig",
    "geringfuegig",
    "lehre",
    "praktikum",
    "traineeship",
}
_NOISE = {
    "neu - bewirb dich gleich",
    "schnelle bewerbung",
    "merken",
    "mehr",
}

_DEFAULT_SEARCHES: tuple[tuple[str, str], ...] = (
    ("konstrukteur-maschinenbau", "Konstrukteur Maschinenbau"),
    ("maschinenbau", "Maschinenbau"),
    ("konstrukteur", "Konstrukteur"),
    ("cad-zeichner", "CAD Zeichner"),
    ("entwicklungsingenieur-in", "Entwicklungsingenieur:in"),
)


@dataclass(frozen=True, slots=True)
class WillhabenSearch:
    slug: str
    label: str


@dataclass(frozen=True, slots=True)
class WillhabenSearchHit:
    job_id: str
    title: str
    url: str
    tail_parts: tuple[str, ...]


class _SearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._anchor_job_id: str | None = None
        self._anchor_href: str | None = None
        self._anchor_parts: list[str] = []
        self._current_job_id: str | None = None
        self._current_title: str | None = None
        self._current_url: str | None = None
        self._current_tail: list[str] = []
        self.hits: list[WillhabenSearchHit] = []
        self.all_text: list[str] = []

    def _finalize_current(self) -> None:
        if self._current_job_id and self._current_title and self._current_url:
            self.hits.append(
                WillhabenSearchHit(
                    job_id=self._current_job_id,
                    title=self._current_title,
                    url=self._current_url,
                    tail_parts=tuple(self._current_tail),
                )
            )
        self._current_job_id = None
        self._current_title = None
        self._current_url = None
        self._current_tail = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        match = _JOB_PATH_RE.search(href)
        if match is None:
            return

        self._finalize_current()
        self._anchor_job_id = match.group("id")
        self._anchor_href = match.group("path")
        self._anchor_parts = []

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split()).strip()
        if not cleaned:
            return
        self.all_text.append(cleaned)
        if self._anchor_job_id is not None:
            self._anchor_parts.append(cleaned)
        elif self._current_job_id is not None:
            self._current_tail.append(cleaned)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._anchor_job_id is None:
            return
        parts = [html.unescape(part).strip() for part in self._anchor_parts if part.strip()]
        if parts:
            self._current_job_id = self._anchor_job_id
            self._current_title = parts[0]
            self._current_url = urljoin(BASE_URL, self._anchor_href or "")
            self._current_tail = parts[1:]
        self._anchor_job_id = None
        self._anchor_href = None
        self._anchor_parts = []

    def close(self) -> None:
        super().close()
        self._finalize_current()


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "noscript", "template"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "template"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.hidden_depth:
            return
        cleaned = " ".join(html.unescape(data).split()).strip()
        if cleaned:
            self.text_parts.append(cleaned)


def _safe_short(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(html.unescape(value).split()).strip()
    if not cleaned or len(cleaned) > max_length:
        return None
    return cleaned


def _compact(parts: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    for part in parts:
        cleaned = " ".join(part.split()).strip()
        if not cleaned or cleaned in result:
            continue
        result.append(cleaned)
        if len(result) >= 16:
            break
    return result


def _company_from_tail(parts: list[str]) -> str | None:
    for part in parts:
        if _META_RE.match(part):
            continue
        if part.casefold() in _NOISE:
            continue
        if part.endswith(" Jobs"):
            return _safe_short(part[:-5], 300)
    for part in parts:
        if _META_RE.match(part) or part.casefold() in _NOISE or len(part) >= 180:
            continue
        return _safe_short(part, 300)
    return None


def _metadata_from_tail(parts: list[str]) -> tuple[str | None, str | None]:
    for part in parts:
        match = _META_RE.match(part)
        if match is None:
            continue
        tokens = [token.strip() for token in match.group("rest").split(",") if token.strip()]
        while tokens and tokens[0].casefold() in _EMPLOYMENT_TOKENS:
            tokens.pop(0)
        return match.group("date"), ", ".join(tokens) or None
    return None, None


def _location(value: str | None) -> RawJobLocation | None:
    text = _safe_short(value, 500)
    if text is None:
        return None
    first = text.split(",", 1)[0].strip()
    postal = _POSTAL_CITY_RE.match(first)
    return RawJobLocation(
        postal_code=postal.group("postal") if postal else None,
        city=(postal.group("city").strip() if postal else first) or None,
        location_text=text,
        remote=False,
    )


def _description_from_tail(parts: list[str], *, company: str | None) -> str | None:
    candidates = [
        part
        for part in parts
        if len(part) >= 100
        and not _META_RE.match(part)
        and part.casefold() not in _NOISE
        and part != company
        and part != f"{company} Jobs"
    ]
    return max(candidates, key=len) if candidates else None


def _detail_salary_text(parts: list[str]) -> str | None:
    """Return a short source-designated salary snippet from a Willhaben detail page."""
    for index, part in enumerate(parts):
        if _SALARY_DETAIL_CUE_RE.search(part) is None:
            continue
        snippet = " ".join(parts[index : index + 3])
        if _SALARY_DETAIL_VALUE_RE.search(snippet):
            return snippet[:500]

    # Some markup places the label and value in adjacent nodes while unrelated text sits
    # between them. The compact full text fallback is still restricted to an explicit
    # salary cue plus a stated EUR period.
    compact = " ".join(parts[:250])
    cue = _SALARY_DETAIL_CUE_RE.search(compact)
    if cue is None:
        return None
    window = compact[cue.start() : cue.start() + 500]
    return window if _SALARY_DETAIL_VALUE_RE.search(window) else None


def enrich_willhaben_detail_page(item: RawJob, content: str) -> RawJob:
    parser = _DetailParser()
    parser.feed(content)
    salary_text = _detail_salary_text(parser.text_parts)
    if salary_text:
        item.salary_text = salary_text

    payload = dict(item.raw_payload)
    payload["detail_enriched"] = True
    payload["willhaben_detail_salary_found"] = salary_text is not None
    payload["acquisition_level"] = "search-card+detail"
    item.raw_payload = payload
    return item


def parse_willhaben_search_page(
    content: str,
    *,
    search_label: str,
) -> tuple[list[RawJob], int | None]:
    parser = _SearchParser()
    parser.feed(content)
    parser.close()

    plain = "\n".join(parser.all_text)
    count_match = _RESULT_COUNT_RE.search(plain)
    reported = None
    if count_match:
        reported = int(count_match.group("count").replace(".", ""))

    jobs: list[RawJob] = []
    for hit in parser.hits:
        title = _safe_short(hit.title, 500)
        if title is None:
            continue
        tail = _compact(hit.tail_parts)
        company = _company_from_tail(tail)
        published_label, location_text = _metadata_from_tail(tail)
        location = _location(location_text)
        description = _description_from_tail(tail, company=company)
        jobs.append(
            RawJob(
                source_listing_id=f"willhabenjobs:{hit.job_id}",
                url=hit.url,
                title=title,
                company=company,
                description=description,
                locations=[location] if location is not None else [],
                raw_payload={
                    "wohnwerk_board": "willhaben-jobs",
                    "willhaben_job_id": hit.job_id,
                    "willhaben_search_label": search_label,
                    "published_label": published_label,
                    "description_truncated_by_source": description is not None,
                    "acquisition_level": "search-result-card",
                },
            )
        )

    return jobs, reported


class WillhabenJobSource(JobSource):
    """Low-impact Willhaben Jobs frontier with bounded relevant-detail enrichment."""

    name = "willhaben-jobs"

    def __init__(
        self,
        *,
        searches: list[WillhabenSearch] | None = None,
        request_delay_seconds: float = 1.0,
        max_details_per_shard: int = 8,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.searches = searches or [WillhabenSearch(*row) for row in _DEFAULT_SEARCHES]
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.max_details_per_shard = max(0, max_details_per_shard)
        self.transport = transport
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._seen_ids: set[str] = set()
        self._detail_cache: dict[str, RawJob] = {}

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=search.slug,
                params={"slug": search.slug, "label": search.label},
                priority=index,
            )
            for index, search in enumerate(self.searches)
        ]

    async def _rate_limit(self) -> None:
        async with self._request_lock:
            remaining = self.request_delay_seconds - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_request_at = time.monotonic()

    async def _request_text(self, client: httpx.AsyncClient, url: str) -> str:
        await self._rate_limit()
        response = await client.get(url)
        response.raise_for_status()
        return response.text

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawJob]:
        del cursor, reconciliation
        slug = shard.params.get("slug")
        label = shard.params.get("label")
        if not isinstance(slug, str) or not isinstance(label, str):
            raise TypeError(f"Invalid willhaben shard params: {shard.params!r}")

        url = f"{BASE_URL}/jobs/suche/{slug}"
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                transport=self.transport,
                headers={
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                    "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
                    "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian job search)",
                },
            ) as client:
                content = await self._request_text(client, url)
                jobs, reported = parse_willhaben_search_page(content, search_label=label)

                items: list[RawJob] = []
                duplicates = 0
                details_fetched = 0
                details_failed = 0
                detail_budget_used = 0

                for job in jobs:
                    if job.source_listing_id in self._seen_ids:
                        duplicates += 1
                        continue
                    self._seen_ids.add(job.source_listing_id)

                    cached = self._detail_cache.get(job.source_listing_id)
                    if cached is not None:
                        items.append(cached)
                        continue

                    if (
                        detail_budget_used < self.max_details_per_shard
                        and _DETAIL_WORTHY_RE.search(job.title)
                    ):
                        detail_budget_used += 1
                        try:
                            detail_content = await self._request_text(client, job.url)
                            job = enrich_willhaben_detail_page(job, detail_content)
                            self._detail_cache[job.source_listing_id] = job
                            details_fetched += 1
                        except Exception as exc:
                            payload = dict(job.raw_payload)
                            payload["detail_enrichment_error"] = f"{type(exc).__name__}: {exc}"
                            job.raw_payload = payload
                            details_failed += 1

                    items.append(job)
        except Exception as exc:
            raise SourceFetchError(
                f"willhaben Jobs shard {shard.key!r} failed: {type(exc).__name__}",
                pages_fetched=1,
            ) from exc

        return SourceBatch(
            items=items,
            next_cursor={
                "strategy": "first-page-search-card-frontier+bounded-detail",
                "search_url": url,
                "search_reported_count": reported,
                "cards_parsed": len(jobs),
                "cross_query_duplicates": duplicates,
                "details_fetched": details_fetched,
                "details_failed": details_failed,
            },
            source_reported_count=reported,
            coverage_complete=False,
            result_cap_hit=False,
            pages_fetched=1 + details_fetched + details_failed,
        )
