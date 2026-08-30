from __future__ import annotations

import asyncio
import html
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

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

BASE_URL = "https://www.palfinger.com"
LIST_PATH = "/worldwide/en/career/jobs.html"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_DETAIL_PATH_RE = re.compile(
    r"^/worldwide/(?:en|de)/career/jobs/[^/?#]+_(?P<posting_id>\d+)\.html$",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")
_POSTAL_LOCATION_RE = re.compile(
    r"\b(?P<postal>\d{4})\s+(?P<city>[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß .'-]*?)\s+AT\b"
)
_SALARY_CUE_RE = re.compile(
    r"\b(?:gehalt|salary|kv-minimum|mindestgehalt|mindestentgelt|entgelt|compensation)\b",
    re.IGNORECASE,
)
_SALARY_CURRENCY_RE = re.compile(r"(?:€|\b(?:EUR|Euro)\b)", re.IGNORECASE)
_DESCRIPTION_STARTS = {
    "was dich erwartet",
    "was sie erwartet",
    "your responsibilities",
    "what you can expect",
    "what awaits you",
}
_DESCRIPTION_STOPS = {
    "quick application",
    "apply with registration",
    "jetzt bewerben",
    "schnellbewerbung",
}
_GENERIC_HEADINGS = {
    "job overview",
    "latest jobs",
    "offene stellen",
    "aktuelle stellenangebote",
}


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: dict[str, str] = {}
        self.page_numbers: set[int] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        href = next((value for key, value in attrs if key.casefold() == "href"), None)
        if not href:
            return
        absolute = urljoin(BASE_URL, href)
        parsed = urlparse(absolute)
        match = _DETAIL_PATH_RE.match(parsed.path)
        if match is not None:
            self.urls.setdefault(match.group("posting_id"), absolute)
        for raw_page in parse_qs(parsed.query).get("page", []):
            try:
                page = int(raw_page)
            except ValueError:
                continue
            if page > 0:
                self.page_numbers.add(page)


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.headings: list[str] = []
        self._heading_depth = 0
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in {"h1", "h2", "h3"}:
            self._heading_depth += 1
            if self._heading_depth == 1:
                self._heading_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() not in {"h1", "h2", "h3"} or not self._heading_depth:
            return
        self._heading_depth -= 1
        if self._heading_depth:
            return
        value = _normalize_text(" ".join(self._heading_parts))
        if value:
            self.headings.append(value)
        self._heading_parts = []

    def handle_data(self, data: str) -> None:
        value = _normalize_text(data)
        if not value:
            return
        self.parts.append(value)
        if self._heading_depth:
            self._heading_parts.append(value)


def _normalize_text(value: str) -> str:
    return html.unescape(_SPACE_RE.sub(" ", value)).strip()


def listing_url(page: int = 1) -> str:
    params = {
        "area": "",
        "city": "",
        "country": "austria",
    }
    if page > 1:
        params["page"] = str(page)
    return f"{BASE_URL}{LIST_PATH}?{urlencode(params)}"


def parse_palfinger_listing_page(value: str) -> tuple[list[tuple[str, str]], int | None]:
    parser = _ListingParser()
    parser.feed(value)
    parser.close()
    max_page = max(parser.page_numbers) if parser.page_numbers else None
    return list(parser.urls.items()), max_page


def _title(headings: list[str]) -> str | None:
    for heading in headings:
        value = heading.strip()
        if value.casefold() in _GENERIC_HEADINGS:
            continue
        if value:
            return value
    return None


def _location(parts: list[str]) -> RawJobLocation | None:
    for value in reversed(parts):
        match = _POSTAL_LOCATION_RE.search(value)
        if match is None:
            continue
        postal = match.group("postal")
        city = _normalize_text(match.group("city"))
        if not city:
            continue
        return RawJobLocation(
            postal_code=postal,
            city=city,
            location_text=f"{postal} {city}, AT",
            remote=False,
        )
    return None


def _description(parts: list[str]) -> str | None:
    start: int | None = None
    for index, value in enumerate(parts):
        if value.casefold().rstrip(":") in _DESCRIPTION_STARTS:
            start = index + 1
            break
    if start is None:
        return None

    selected: list[str] = []
    for value in parts[start:]:
        if value.casefold().rstrip(":") in _DESCRIPTION_STOPS:
            break
        selected.append(value)
    text = "\n".join(selected).strip()
    return text or None


def _salary_text(parts: list[str]) -> str | None:
    for index, value in enumerate(parts):
        for width in (1, 2, 3):
            selected = parts[index : index + width]
            if not selected:
                continue
            text = _normalize_text(" ".join(selected))
            if _SALARY_CUE_RE.search(text) and _SALARY_CURRENCY_RE.search(text):
                return text
    return None


def parse_palfinger_detail_page(value: str, *, posting_id: str, url: str) -> RawJob:
    parser = _DetailParser()
    parser.feed(value)
    parser.close()

    title = _title(parser.headings)
    if title is None:
        raise ValueError("PALFINGER detail page has no job title")
    location = _location(parser.parts)
    if location is None:
        raise ValueError("PALFINGER Austrian detail page has no source-backed AT location")
    description = _description(parser.parts)
    if description is None:
        raise ValueError("PALFINGER detail page has no supported responsibilities section")

    payload = with_stable_identity(
        {
            "wohnwerk_board": "palfinger-direct-careers",
            "wohnwerk_company": "PALFINGER",
            "palfinger_posting_id": posting_id,
            "palfinger_location_text": location.location_text,
        },
        f"direct:palfinger:{posting_id}",
    )
    return RawJob(
        source_listing_id=f"palfinger:{posting_id}",
        url=url,
        title=title,
        company="PALFINGER",
        description=description,
        salary_text=_salary_text(parser.parts),
        locations=[location],
        raw_payload=payload,
    )


class PalfingerJobSource(JobSource):
    """Complete PALFINGER Austria public career pages with source-backed details."""

    name = "palfinger-direct-careers"

    def __init__(
        self,
        *,
        request_delay_seconds: float = 0.10,
        hard_max_pages: int = 20,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.hard_max_pages = max(1, hard_max_pages)
        self.timeout_seconds = timeout_seconds

    def default_shards(self) -> list[SourceShardSpec]:
        return [SourceShardSpec(key="palfinger-austria-careers")]

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
        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en,en-GB;q=0.9,de-AT;q=0.7",
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian job search)",
        }
        pages_fetched = 0
        listing_pages_fetched = 0
        postings: dict[str, str] = {}
        items: list[RawJob] = []
        detail_attempted = 0
        detail_missing = 0
        detail_failed = 0
        failed_ids: list[str] = []
        pagination_failed = False
        cap_hit = False
        expected_pages: int | None = None

        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            try:
                status, first_html = await self._request_text(client, listing_url(1))
                pages_fetched += 1
                listing_pages_fetched += 1
                if status == 404:
                    raise ValueError("PALFINGER Austria listing returned 404")
                first_postings, first_max_page = parse_palfinger_listing_page(first_html)
                if not first_postings:
                    raise ValueError("PALFINGER Austria listing contains no detail links")
                postings.update(first_postings)
                expected_pages = first_max_page
                if expected_pages is None:
                    pagination_failed = True
                elif expected_pages > self.hard_max_pages:
                    cap_hit = True
                else:
                    for page in range(2, expected_pages + 1):
                        status, page_html = await self._request_text(client, listing_url(page))
                        pages_fetched += 1
                        listing_pages_fetched += 1
                        if status == 404:
                            pagination_failed = True
                            break
                        page_postings, page_max_page = parse_palfinger_listing_page(page_html)
                        if page_max_page is not None:
                            expected_pages = max(expected_pages, page_max_page)
                        if not page_postings:
                            pagination_failed = True
                            break
                        before = len(postings)
                        postings.update(page_postings)
                        if len(postings) == before:
                            pagination_failed = True
                            break

                if not postings:
                    raise ValueError("PALFINGER Austria listing materialized no jobs")

                for posting_id, detail_url in postings.items():
                    detail_attempted += 1
                    try:
                        status, detail_html = await self._request_text(client, detail_url)
                        pages_fetched += 1
                        if status == 404:
                            detail_missing += 1
                            continue
                        parsed = parse_palfinger_detail_page(
                            detail_html,
                            posting_id=posting_id,
                            url=detail_url,
                        )
                    except (httpx.HTTPError, TypeError, ValueError) as exc:
                        detail_failed += 1
                        failed_ids.append(f"{posting_id}:{type(exc).__name__}")
                        continue
                    items.append(parsed)

                coverage_complete = (
                    not cap_hit
                    and not pagination_failed
                    and detail_failed == 0
                    and expected_pages is not None
                    and listing_pages_fetched >= expected_pages
                )
                return SourceBatch(
                    items=items,
                    next_cursor={
                        "job_candidates_fetched": len(items),
                        "listing_pages_fetched": listing_pages_fetched,
                        "listing_expected_pages": expected_pages,
                        "listing_detail_urls": len(postings),
                        "pagination_failed": pagination_failed,
                        "detail_attempted": detail_attempted,
                        "detail_missing": detail_missing,
                        "detail_failed": detail_failed,
                        "detail_failed_ids": failed_ids,
                        "austrian_postings": len(items),
                    },
                    source_reported_count=len(postings),
                    coverage_complete=coverage_complete,
                    result_cap_hit=cap_hit,
                    pages_fetched=pages_fetched,
                )
            except (httpx.HTTPError, TypeError, ValueError) as exc:
                raise SourceFetchError(
                    f"PALFINGER shard {shard.key!r} failed: {exc}",
                    pages_fetched=pages_fetched,
                    items_seen=len(items),
                    source_reported_count=len(postings) or None,
                    next_cursor={
                        "listing_pages_fetched": listing_pages_fetched,
                        "listing_expected_pages": expected_pages,
                        "pagination_failed": pagination_failed,
                        "detail_attempted": detail_attempted,
                        "detail_failed": detail_failed,
                    },
                    partial_items=items,
                ) from exc
