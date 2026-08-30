from __future__ import annotations

import asyncio
import html
import math
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.jobs.identity import with_stable_identity
from app.sources.base import (
    JobSource,
    RawJob,
    RawJobLocation,
    SourceBatch,
    SourceFetchError,
    SourceShardSpec,
)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_JOB_URL_RE = re.compile(r"/job/[^?#]+/(?P<posting_id>\d+)/?", re.IGNORECASE)
_RESULT_TOTAL_RE = re.compile(
    r"(?:Results|Ergebnisse)\s+\d+\s*[–—-]\s*\d+\s+(?:of|von)\s+(\d+)",
    re.IGNORECASE,
)
_AUSTRIA_RE = re.compile(r"\b(?:Austria|Österreich|Oesterreich)\b", re.IGNORECASE)
_AT_LOCATION_RE = re.compile(r"(?:^|[\s,;|])AT(?=$|[\s,;|])")
_REMOTE_RE = re.compile(r"\b(?:remote|home\s*office|homeoffice)\b", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")
_LOCATION_SPLIT_RE = re.compile(r"\s+(?:or|oder)\s+|\s*;\s*", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SuccessFactorsSite:
    tenant: str
    company: str
    origin: str
    search_path: str
    page_size: int = 25

    def __post_init__(self) -> None:
        if not self.tenant.strip():
            raise ValueError("SuccessFactors tenant must not be empty")
        if not self.company.strip():
            raise ValueError("SuccessFactors company must not be empty")
        if not self.origin.startswith("https://"):
            raise ValueError("SuccessFactors origin must be HTTPS")
        if not self.search_path.startswith("/"):
            raise ValueError("SuccessFactors search_path must be absolute")
        if self.page_size <= 0:
            raise ValueError("SuccessFactors page_size must be positive")

    def search_url(self, offset: int) -> str:
        path = self.search_path.rstrip("/")
        return (
            f"{self.origin.rstrip('/')}{path}/{offset}/"
            "?q=&sortColumn=referencedate&sortDirection=desc"
        )


@dataclass(frozen=True, slots=True)
class _SearchPosting:
    url: str
    row_text: str


class _SearchPageParser(HTMLParser):
    def __init__(self, *, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.text_parts: list[str] = []
        self.postings: list[_SearchPosting] = []
        self._in_row = 0
        self._row_parts: list[str] = []
        self._row_urls: list[str] = []
        self._fallback_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "tr":
            self._in_row += 1
            if self._in_row == 1:
                self._row_parts = []
                self._row_urls = []
            return
        if tag.casefold() != "a":
            return
        href = next((value for key, value in attrs if key.casefold() == "href"), None)
        if not href:
            return
        absolute = urljoin(self.base_url, href)
        if _JOB_URL_RE.search(urlparse(absolute).path):
            self._fallback_urls.append(absolute)
            if self._in_row:
                self._row_urls.append(absolute)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "tr" or not self._in_row:
            return
        self._in_row -= 1
        if self._in_row:
            return
        row_text = _normalize_text(" ".join(self._row_parts))
        for url in dict.fromkeys(self._row_urls):
            self.postings.append(_SearchPosting(url=url, row_text=row_text))
        self._row_parts = []
        self._row_urls = []

    def handle_data(self, data: str) -> None:
        cleaned = data.strip()
        if not cleaned:
            return
        self.text_parts.append(cleaned)
        if self._in_row:
            self._row_parts.append(cleaned)

    def finish(self) -> tuple[list[_SearchPosting], int | None]:
        if not self.postings:
            self.postings = [
                _SearchPosting(url=url, row_text="")
                for url in dict.fromkeys(self._fallback_urls)
            ]
        else:
            unique: dict[str, _SearchPosting] = {}
            for posting in self.postings:
                unique.setdefault(posting.url, posting)
            self.postings = list(unique.values())

        page_text = _normalize_text(" ".join(self.text_parts))
        match = _RESULT_TOTAL_RE.search(page_text)
        total = int(match.group(1)) if match else None
        return self.postings, total


class _DetailPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._in_h1 = 0
        self._h1_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() == "h1":
            self._in_h1 += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "h1" and self._in_h1:
            self._in_h1 -= 1

    def handle_data(self, data: str) -> None:
        cleaned = _normalize_text(data)
        if not cleaned:
            return
        self.blocks.append(cleaned)
        if self._in_h1:
            self._h1_parts.append(cleaned)

    @property
    def heading(self) -> str | None:
        value = _normalize_text(" ".join(self._h1_parts))
        return value or None


def _normalize_text(value: str) -> str:
    return html.unescape(_SPACE_RE.sub(" ", value)).strip()


def _parse_search_page(value: str, *, base_url: str) -> tuple[list[_SearchPosting], int | None]:
    parser = _SearchPageParser(base_url=base_url)
    parser.feed(value)
    parser.close()
    return parser.finish()


def _strip_heading_label(value: str) -> str:
    for label in ("Job title:", "Bezeichnung:"):
        if value.casefold().startswith(label.casefold()):
            return value[len(label) :].strip()
    return value.strip()


def _label_value(blocks: list[str], labels: tuple[str, ...]) -> str | None:
    normalized_labels = tuple(label.casefold() for label in labels)
    for index, block in enumerate(blocks):
        folded = block.casefold()
        for label, normalized in zip(labels, normalized_labels, strict=True):
            if folded == normalized and index + 1 < len(blocks):
                return blocks[index + 1].strip() or None
            if folded.startswith(normalized):
                value = block[len(label) :].strip()
                if value:
                    return value
    return None


def _description(blocks: list[str]) -> str | None:
    starts = {"description:", "job description:", "beschreibung:"}
    stops = (
        "contact person:",
        "ansprechperson:",
        "job requisition id:",
        "stellenanforderungs-id:",
        "similar jobs",
        "ähnliche stellen",
    )
    start_index: int | None = None
    for index, block in enumerate(blocks):
        folded = block.casefold()
        if folded in starts:
            start_index = index + 1
            break
        for label in starts:
            if folded.startswith(label):
                remainder = block[len(label) :].strip()
                pieces = ([remainder] if remainder else []) + blocks[index + 1 :]
                return _description_until_stop(pieces, stops)
    if start_index is None:
        return None
    return _description_until_stop(blocks[start_index:], stops)


def _description_until_stop(blocks: list[str], stops: tuple[str, ...]) -> str | None:
    selected: list[str] = []
    for block in blocks:
        folded = block.casefold()
        if any(folded.startswith(stop) for stop in stops):
            break
        selected.append(block)
    value = "\n".join(selected).strip()
    return value or None


def _looks_austrian(value: str) -> bool:
    return bool(_AUSTRIA_RE.search(value) or _AT_LOCATION_RE.search(value))


def _locations(value: str) -> list[RawJobLocation]:
    parts = [part.strip() for part in _LOCATION_SPLIT_RE.split(value) if part.strip()]
    if not parts:
        parts = [value.strip()]
    locations: list[RawJobLocation] = []
    seen: set[str] = set()
    for part in parts:
        if not _looks_austrian(part):
            continue
        key = part.casefold()
        if key in seen:
            continue
        seen.add(key)
        city = part.split(",", 1)[0].strip()
        if city.casefold() in {"austria", "österreich", "oesterreich", "at"}:
            city = ""
        locations.append(
            RawJobLocation(
                city=city or None,
                location_text=part,
                remote=bool(_REMOTE_RE.search(part)),
            )
        )
    return locations


def parse_successfactors_detail(
    value: str,
    *,
    site: SuccessFactorsSite,
    url: str,
) -> RawJob | None:
    parser = _DetailPageParser()
    parser.feed(value)
    parser.close()
    blocks = parser.blocks

    heading = parser.heading
    if heading is None:
        raise ValueError("SuccessFactors detail page has no h1 title")
    title = _strip_heading_label(heading)
    if not title:
        raise ValueError("SuccessFactors detail page has an empty title")

    location_text = _label_value(
        blocks,
        ("Contract location:", "Arbeitsvertraglicher Standort:"),
    )
    if location_text is None or not _looks_austrian(location_text):
        return None
    locations = _locations(location_text)
    if not locations:
        return None

    requisition_id = _label_value(
        blocks,
        ("Job requisition ID:", "Stellenanforderungs-ID:"),
    )
    url_match = _JOB_URL_RE.search(urlparse(url).path)
    posting_id = url_match.group("posting_id") if url_match else None
    stable_id = requisition_id or posting_id
    if stable_id is None:
        raise ValueError("SuccessFactors detail page has no stable posting id")

    raw_payload = with_stable_identity(
        {
            "wohnwerk_successfactors_tenant": site.tenant,
            "wohnwerk_company": site.company,
            "successfactors_requisition_id": requisition_id,
            "successfactors_posting_id": posting_id,
            "successfactors_contract_location": location_text,
        },
        f"successfactors:{site.tenant}:req:{stable_id}",
    )

    return RawJob(
        source_listing_id=f"{site.tenant}:{stable_id}",
        url=url,
        title=title,
        company=site.company,
        description=_description(blocks),
        locations=locations,
        raw_payload=raw_payload,
    )


class SuccessFactorsJobSource(JobSource):
    """Complete public SAP SuccessFactors career microsites for selected employers."""

    name = "successfactors-public-career-site"

    def __init__(
        self,
        *,
        sites: list[SuccessFactorsSite],
        request_delay_seconds: float = 0.15,
        hard_max_pages: int = 100,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not sites:
            raise ValueError("At least one SuccessFactors site is required")
        self.sites = list(sites)
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.hard_max_pages = max(1, hard_max_pages)
        self.timeout_seconds = timeout_seconds

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=site.tenant,
                params={
                    "tenant": site.tenant,
                    "company": site.company,
                    "origin": site.origin,
                    "search_path": site.search_path,
                    "page_size": site.page_size,
                },
            )
            for site in self.sites
        ]

    @staticmethod
    def _site_from_shard(shard: SourceShardSpec) -> SuccessFactorsSite:
        params = shard.params
        tenant = params.get("tenant")
        company = params.get("company")
        origin = params.get("origin")
        search_path = params.get("search_path")
        page_size = params.get("page_size", 25)
        if not all(
            isinstance(value, str) and value.strip()
            for value in (tenant, company, origin, search_path)
        ):
            raise TypeError(f"Invalid SuccessFactors shard parameters for {shard.key!r}")
        if not isinstance(page_size, int):
            raise TypeError(f"Invalid SuccessFactors page size for {shard.key!r}")
        return SuccessFactorsSite(
            tenant=tenant,
            company=company,
            origin=origin,
            search_path=search_path,
            page_size=page_size,
        )

    async def _request_text(self, client: httpx.AsyncClient, url: str) -> tuple[int, str]:
        last_error: Exception | None = None
        for attempt in range(3):
            if self.request_delay_seconds > 0:
                await asyncio.sleep(self.request_delay_seconds)
            try:
                response = await client.get(url)
                if response.status_code == 404:
                    return 404, ""
                response.raise_for_status()
                return response.status_code, response.text
            except httpx.HTTPError as exc:
                last_error = exc
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    exc.response.status_code in _RETRYABLE_STATUS
                )
                if attempt == 2 or not retryable:
                    raise
                await asyncio.sleep(2**attempt)
        raise RuntimeError("unreachable") from last_error

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawJob]:
        del cursor, reconciliation
        site = self._site_from_shard(shard)
        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "de-AT,de;q=0.9,en;q=0.7",
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian job search)",
        }
        pages_fetched = 0
        source_reported: int | None = None
        candidate_urls: list[str] = []
        seen_urls: set[str] = set()
        offset = 0
        cap_hit = False

        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            try:
                while True:
                    if pages_fetched >= self.hard_max_pages:
                        cap_hit = True
                        break
                    search_url = site.search_url(offset)
                    status, page_html = await self._request_text(client, search_url)
                    if status == 404:
                        if offset == 0:
                            raise ValueError("SuccessFactors search page returned 404")
                        break
                    postings, page_total = _parse_search_page(page_html, base_url=site.origin)
                    pages_fetched += 1
                    if page_total is not None:
                        source_reported = max(source_reported or 0, page_total)

                    for posting in postings:
                        if posting.url in seen_urls:
                            continue
                        seen_urls.add(posting.url)
                        if not posting.row_text or _looks_austrian(posting.row_text):
                            candidate_urls.append(posting.url)

                    if source_reported is not None:
                        expected_pages = max(1, math.ceil(source_reported / site.page_size))
                        if pages_fetched >= expected_pages:
                            break
                    if len(postings) < site.page_size:
                        break
                    offset += site.page_size

                items: list[RawJob] = []
                for detail_url in candidate_urls:
                    status, detail_html = await self._request_text(client, detail_url)
                    pages_fetched += 1
                    if status == 404:
                        continue
                    parsed = parse_successfactors_detail(
                        detail_html,
                        site=site,
                        url=detail_url,
                    )
                    if parsed is not None:
                        items.append(parsed)

                search_pages = (
                    min(self.hard_max_pages, math.ceil(source_reported / site.page_size))
                    if source_reported is not None
                    else None
                )
                return SourceBatch(
                    items=items,
                    next_cursor={
                        "candidate_detail_urls": len(candidate_urls),
                        "search_pages": search_pages,
                    },
                    source_reported_count=source_reported,
                    coverage_complete=not cap_hit,
                    result_cap_hit=cap_hit,
                    pages_fetched=pages_fetched,
                )
            except (httpx.HTTPError, TypeError, ValueError) as exc:
                raise SourceFetchError(
                    f"SuccessFactors shard {shard.key!r} failed: {exc}",
                    pages_fetched=pages_fetched,
                    items_seen=0,
                    source_reported_count=source_reported,
                    next_cursor={"offset": offset},
                    partial_items=[],
                ) from exc
