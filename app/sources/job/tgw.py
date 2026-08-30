from __future__ import annotations

import asyncio
import html
import re
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

BASE_URL = "https://www.tgw-group.com"
LIST_URL = f"{BASE_URL}/en/career/jobs/"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_DETAIL_PATH_RE = re.compile(
    r"^/en/career/jobs/detail/(?P<slug>[^/?#]+)-(?P<posting_id>\d+)/?$",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")
_TITLE_FOOTNOTE_RE = re.compile(r"\s*\*\s*$")
_AUSTRIAN_LOCATION_RE = re.compile(r"^(.+?),\s*Austria(?:\s.*)?$", re.IGNORECASE)


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        href = next((value for key, value in attrs if key.casefold() == "href"), None)
        if not href:
            return
        absolute = urljoin(BASE_URL, href)
        match = _DETAIL_PATH_RE.match(urlparse(absolute).path)
        if match is None:
            return
        self.urls.setdefault(match.group("posting_id"), absolute)


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
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
        self.text_parts.append(value)
        if self._heading_depth:
            self._heading_parts.append(value)


def _normalize_text(value: str) -> str:
    return html.unescape(_SPACE_RE.sub(" ", value)).strip()


def parse_tgw_listing_page(value: str) -> list[tuple[str, str]]:
    parser = _ListingParser()
    parser.feed(value)
    parser.close()
    return list(parser.urls.items())


def _main_title(headings: list[str]) -> str | None:
    for index, heading in enumerate(headings[:-1]):
        if heading.casefold().rstrip("!") == "join team possible":
            title = _TITLE_FOOTNOTE_RE.sub("", headings[index + 1]).strip()
            return title or None
    for heading in headings:
        folded = heading.casefold().rstrip("!")
        if folded in {"join team possible", "our open positions"}:
            continue
        if "career" in folded or "jobs" == folded:
            continue
        title = _TITLE_FOOTNOTE_RE.sub("", heading).strip()
        if title:
            return title
    return None


def _first_index(values: list[str], labels: tuple[str, ...], *, start: int = 0) -> int | None:
    normalized = {label.casefold() for label in labels}
    for index in range(start, len(values)):
        if values[index].casefold() in normalized:
            return index
    return None


def _main_start(parts: list[str]) -> int:
    for index, value in enumerate(parts):
        if value.casefold().rstrip("!") == "join team possible":
            return index
    return 0


def _location_after_title(parts: list[str]) -> RawJobLocation | None:
    start = _main_start(parts)
    stop = _first_index(
        parts,
        ("What you'll be handling:", "What you’ll be handling:"),
        start=start,
    )
    stop = stop if stop is not None else min(len(parts), start + 40)
    for value in parts[start:stop]:
        match = _AUSTRIAN_LOCATION_RE.match(value)
        if match is None:
            continue
        city = match.group(1).strip()
        if not city:
            continue
        return RawJobLocation(city=city, location_text=value, remote=False)
    return None


def _description(parts: list[str]) -> str | None:
    main_start = _main_start(parts)
    start = _first_index(
        parts,
        ("What you'll be handling:", "What you’ll be handling:"),
        start=main_start,
    )
    if start is None:
        start = main_start + 1
    stop = _first_index(
        parts,
        ("What you'll receive:", "What you’ll receive:"),
        start=start,
    )
    if stop is None:
        stop = _first_index(parts, ("Ready to start?",), start=start)
    stop = stop if stop is not None else min(len(parts), start + 100)
    selected = parts[start:stop]
    value = "\n".join(selected).strip()
    return value or None


def parse_tgw_detail_page(value: str, *, posting_id: str, url: str) -> RawJob | None:
    parser = _DetailParser()
    parser.feed(value)
    parser.close()

    title = _main_title(parser.headings)
    if title is None:
        raise ValueError("TGW detail page has no job title")
    location = _location_after_title(parser.text_parts)
    if location is None:
        return None

    payload = with_stable_identity(
        {
            "wohnwerk_board": "tgw-direct-careers",
            "wohnwerk_company": "TGW Logistics",
            "tgw_posting_id": posting_id,
            "tgw_location_text": location.location_text,
        },
        f"direct:tgw:{posting_id}",
    )
    return RawJob(
        source_listing_id=f"tgw:{posting_id}",
        url=url,
        title=title,
        company="TGW Logistics",
        description=_description(parser.text_parts),
        locations=[location],
        raw_payload=payload,
    )


class TGWJobSource(JobSource):
    """Complete public TGW career listing with source-backed Austrian details."""

    name = "tgw-direct-careers"

    def __init__(
        self,
        *,
        request_delay_seconds: float = 0.10,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.timeout_seconds = timeout_seconds

    def default_shards(self) -> list[SourceShardSpec]:
        return [SourceShardSpec(key="tgw-public-careers")]

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
        items: list[RawJob] = []
        detail_attempted = 0
        detail_missing = 0
        detail_failed = 0
        failed_ids: list[str] = []

        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            try:
                status, listing_html = await self._request_text(client, LIST_URL)
                pages_fetched += 1
                if status == 404:
                    raise ValueError("TGW careers listing returned 404")
                postings = parse_tgw_listing_page(listing_html)
                if not postings:
                    raise ValueError("TGW careers listing contains no detail links")

                for posting_id, detail_url in postings:
                    detail_attempted += 1
                    try:
                        status, detail_html = await self._request_text(client, detail_url)
                        pages_fetched += 1
                        if status == 404:
                            detail_missing += 1
                            continue
                        parsed = parse_tgw_detail_page(
                            detail_html,
                            posting_id=posting_id,
                            url=detail_url,
                        )
                    except (httpx.HTTPError, TypeError, ValueError) as exc:
                        detail_failed += 1
                        failed_ids.append(f"{posting_id}:{type(exc).__name__}")
                        continue
                    if parsed is not None:
                        items.append(parsed)

                return SourceBatch(
                    items=items,
                    next_cursor={
                        "job_candidates_fetched": len(items),
                        "listing_detail_urls": len(postings),
                        "detail_attempted": detail_attempted,
                        "detail_missing": detail_missing,
                        "detail_failed": detail_failed,
                        "detail_failed_ids": failed_ids,
                        "austrian_postings": len(items),
                    },
                    source_reported_count=len(postings),
                    coverage_complete=detail_failed == 0,
                    result_cap_hit=False,
                    pages_fetched=pages_fetched,
                )
            except (httpx.HTTPError, TypeError, ValueError) as exc:
                raise SourceFetchError(
                    f"TGW shard {shard.key!r} failed: {exc}",
                    pages_fetched=pages_fetched,
                    items_seen=len(items),
                    source_reported_count=None,
                    next_cursor={
                        "detail_attempted": detail_attempted,
                        "detail_failed": detail_failed,
                    },
                    partial_items=items,
                ) from exc
