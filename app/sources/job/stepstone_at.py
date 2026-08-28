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

BASE_URL = "https://www.stepstone.at"

_JOB_PATH_RE = re.compile(
    r"(?:https?://(?:www\.)?stepstone\.at)?"
    r"(?P<path>/stellenangebote--[^\"'?#]+--(?P<id>\d+)-inline\.html)"
)
_RESULT_COUNT_RE = re.compile(r"(?<!\d)(\d{1,4})\s+Treffer\b", re.IGNORECASE)
_POSTAL_CITY_RE = re.compile(r"^(?P<postal>\d{4})(?:\s+(?P<city>.+))?$")
_RELATIVE_AGE_RE = re.compile(
    r"^(?:vor\s+\d+\s+(?:Stunden?|Tagen?|Wochen?|Monaten?)|heute|gestern)$",
    re.IGNORECASE,
)
_STYLE_NOISE_RE = re.compile(
    r"(?:box-sizing:|@media\b|#no-js-image|data-genesis-element|"
    r"display\s*:\s*none|\.res-[a-z0-9_-]+\s*\{|\}\s*\.res-)",
    re.IGNORECASE,
)
_TITLE_NOISE = {
    "mehr",
    "neu",
    "schnelle bewerbung",
    "teilweise home-office",
}

_REGIONS = {
    "burgenland",
    "kärnten",
    "kaernten",
    "niederösterreich",
    "niederoesterreich",
    "oberösterreich",
    "oberoesterreich",
    "salzburg",
    "steiermark",
    "tirol",
    "vorarlberg",
    "wien",
    "österreich",
    "oesterreich",
    "österreichweit",
    "oesterreichweit",
    "ostösterreich",
    "ostoesterreich",
    "westösterreich",
    "westoesterreich",
    "südösterreich",
    "suedoesterreich",
}

_DEFAULT_SEARCHES: tuple[tuple[str, str], ...] = (
    ("konstrukteur-maschinenbau", "Konstrukteur Maschinenbau"),
    ("maschinenbauingenieur", "Maschinenbauingenieur"),
    ("mechanical-engineer", "Mechanical Engineer"),
    ("entwicklungsingenieur-maschinenbau", "Entwicklungsingenieur Maschinenbau"),
    ("projektingenieur-maschinenbau", "Projektingenieur Maschinenbau"),
)


@dataclass(frozen=True, slots=True)
class StepStoneSearch:
    slug: str
    label: str


@dataclass(frozen=True, slots=True)
class StepStoneSearchHit:
    job_id: str
    title: str
    url: str
    tail_parts: tuple[str, ...]


def _is_markup_noise(value: str) -> bool:
    cleaned = " ".join(html.unescape(value).split()).strip()
    if not cleaned:
        return True
    folded = cleaned.casefold()
    if folded in _TITLE_NOISE:
        return True
    return bool(_STYLE_NOISE_RE.search(cleaned))


def _human_anchor_fragment(value: str) -> str | None:
    cleaned = " ".join(html.unescape(value).split()).strip()
    if not cleaned:
        return None

    if _STYLE_NOISE_RE.search(cleaned):
        # Emotion/no-js styles can be emitted in the same HTML text node as the
        # visible title. Keep only the human suffix after the final CSS block.
        if "}" not in cleaned:
            return None
        cleaned = cleaned.rsplit("}", 1)[-1].strip()

    if (
        not cleaned
        or len(cleaned) > 500
        or cleaned.casefold() in _TITLE_NOISE
        or _STYLE_NOISE_RE.search(cleaned)
    ):
        return None
    return cleaned


def _title_part(parts: list[str]) -> tuple[int, str] | None:
    for index, part in enumerate(parts):
        human = _human_anchor_fragment(part)
        if human is not None:
            return index, human
    return None


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
        self.hits: list[StepStoneSearchHit] = []
        self.all_text: list[str] = []

    def _finalize_current(self) -> None:
        if self._current_job_id and self._current_title and self._current_url:
            self.hits.append(
                StepStoneSearchHit(
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
        if not match:
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

        # Live StepStone cards expose multiple links to the same vacancy. Logo links
        # can contain only Emotion/no-js CSS, while title links can contain CSS before
        # the actual human title. Never promote those style fragments into a job row.
        anchor_parts = [html.unescape(part).strip() for part in self._anchor_parts if part.strip()]
        title_part = _title_part(anchor_parts)
        if title_part is not None:
            title_index, title = title_part
            self._current_job_id = self._anchor_job_id
            self._current_title = title
            self._current_url = urljoin(BASE_URL, self._anchor_href or "")
            self._current_tail = [
                part
                for part in anchor_parts[title_index + 1 :]
                if not _is_markup_noise(part)
            ]

        self._anchor_job_id = None
        self._anchor_href = None
        self._anchor_parts = []

    def close(self) -> None:
        super().close()
        self._finalize_current()


def _compact_tail(parts: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    for part in parts:
        cleaned = " ".join(html.unescape(part).split()).strip()
        if not cleaned or _is_markup_noise(cleaned) or cleaned in result:
            continue
        result.append(cleaned)
        if len(result) >= 12:
            break
    return result


def _safe_short_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(html.unescape(value).split()).strip()
    if not cleaned or len(cleaned) > max_length or _is_markup_noise(cleaned):
        return None
    return cleaned


def _location_from_text(value: str | None) -> RawJobLocation | None:
    text = _safe_short_text(value, max_length=500)
    if text is None:
        return None

    first = text.split(",", 1)[0].strip()
    postal_match = _POSTAL_CITY_RE.match(first)
    if postal_match:
        city = postal_match.group("city")
        return RawJobLocation(
            postal_code=postal_match.group("postal"),
            city=city.strip() if city and city.strip() else None,
            location_text=text,
            remote=False,
        )

    parts = [part.strip() for part in text.split(",") if part.strip()]
    city: str | None = None
    if parts:
        if parts[0].casefold() not in _REGIONS:
            city = parts[0]
        elif len(parts) > 1 and parts[1].casefold() not in _REGIONS:
            city = parts[1]

    return RawJobLocation(
        postal_code=None,
        city=city,
        location_text=text,
        remote=False,
    )


def parse_stepstone_search_page(
    content: str,
    *,
    search_label: str,
) -> tuple[list[RawJob], int | None]:
    parser = _SearchParser()
    parser.feed(content)
    parser.close()

    plain = "\n".join(parser.all_text)
    count_match = _RESULT_COUNT_RE.search(plain)
    reported = int(count_match.group(1)) if count_match else None

    jobs: list[RawJob] = []
    for hit in parser.hits:
        title = _safe_short_text(hit.title, max_length=500)
        if title is None:
            continue

        tail = _compact_tail(hit.tail_parts)
        if not tail:
            company = None
            location_text = None
            description = None
        else:
            company = _safe_short_text(tail[0], max_length=300)
            location_text = _safe_short_text(tail[1], max_length=500) if len(tail) > 1 else None
            description = next(
                (
                    part
                    for part in tail[2:]
                    if len(part) >= 60
                    and part.casefold() not in {"schnelle bewerbung", "teilweise home-office"}
                    and not _RELATIVE_AGE_RE.match(part)
                    and not _is_markup_noise(part)
                ),
                None,
            )

        location = _location_from_text(location_text)
        jobs.append(
            RawJob(
                source_listing_id=f"stepstoneat:{hit.job_id}",
                url=hit.url,
                title=title,
                company=company,
                description=description,
                locations=[location] if location is not None else [],
                raw_payload={
                    "wohnwerk_board": "stepstone.at",
                    "stepstone_job_id": hit.job_id,
                    "stepstone_search_label": search_label,
                    "description_truncated_by_source": description is not None,
                    "acquisition_level": "search-result-card",
                },
            )
        )

    return jobs, reported


class StepStoneAtJobSource(JobSource):
    """Very low-impact StepStone Austria frontier using search-result cards only."""

    name = "stepstone.at"

    def __init__(
        self,
        *,
        searches: list[StepStoneSearch] | None = None,
        request_delay_seconds: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.searches = searches or [StepStoneSearch(*row) for row in _DEFAULT_SEARCHES]
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.transport = transport
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._seen_ids: set[str] = set()

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
            raise TypeError(f"Invalid StepStone shard params: {shard.params!r}")

        url = f"{BASE_URL}/jobs/{slug}"
        await self._rate_limit()
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
                response = await client.get(url)
                response.raise_for_status()
        except Exception as exc:
            raise SourceFetchError(
                f"StepStone Austria shard {shard.key!r} failed: {type(exc).__name__}",
                pages_fetched=1,
            ) from exc

        jobs, reported = parse_stepstone_search_page(response.text, search_label=label)
        items: list[RawJob] = []
        duplicates = 0
        for job in jobs:
            if job.source_listing_id in self._seen_ids:
                duplicates += 1
                continue
            self._seen_ids.add(job.source_listing_id)
            items.append(job)

        return SourceBatch(
            items=items,
            next_cursor={
                "strategy": "search-result-card-frontier",
                "search_url": url,
                "search_reported_count": reported,
                "cards_parsed": len(jobs),
                "cross_query_duplicates": duplicates,
                "details_fetched": 0,
            },
            source_reported_count=reported,
            coverage_complete=False,
            result_cap_hit=False,
            pages_fetched=1,
        )
