from __future__ import annotations

import asyncio
import html
import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Iterator
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

BASE_URL = "https://www.jobs.at"

_JOB_PATH_RE = re.compile(r"(?:https?://(?:www\.)?jobs\.at)?/i/(\d+)(?:[/?#]|$)")
_WS_RE = re.compile(r"\s+")
_RESULT_COUNT_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*|\d+)\s+aktuelle\b[^\n]{0,100}?Jobs\b",
    re.IGNORECASE,
)
_VISIBLE_AGE_RE = re.compile(
    r"^(?:heute|gestern|vor\s+\d+\s*[tT]|vor\s+\d+\s+Tag|online\s+gestellt\s+vor)",
    re.IGNORECASE,
)
_POSTAL_CITY_RE = re.compile(r"^(?P<postal>\d{4})\s+(?P<city>.+)$")
_VISIBLE_SALARY_RE = re.compile(
    r"(?P<salary>(?:ab\s+)?\d[\d.\s]*(?:,\d+)?\s*€\s+pro\s+(?:Monat|Jahr|Stunde))",
    re.IGNORECASE,
)

# Request-budget filter only. The actual professional-relevance decision is still
# app.jobs.discovery after detail acquisition.
_DETAIL_WORTHY_RE = re.compile(
    r"(?:konstruk|maschinenbau|mechanical|cad|entwicklungsingenieur|"
    r"development\s+engineer|design\s+engineer|project\s+engineer|projektingenieur|"
    r"technisch\w*\s+projekt|projektleiter|sondermaschinen|fahrzeug|automotive|"
    r"berechnungsingenieur|simulation\s+engineer|product\s+engineer|"
    r"mechanik|baugruppen|antrieb|chassis|quality\s+engineer.*mechanical)",
    re.IGNORECASE,
)
_DETAIL_SKIP_RE = re.compile(
    r"(?:elektro|electrical|eplan|software|full[-\s]*stack|data\s+(?:engineer|scientist)|"
    r"sales|vertrieb|lehr(?:e|ausbildung)|trainee|internship|werkstudent|"
    r"kfz[-/\s]*(?:mechaniker|techniker|mechatroniker)|karosseriebautechniker)",
    re.IGNORECASE,
)

_DEFAULT_SEARCHES: tuple[tuple[str, str], ...] = (
    ("mechanical-engineer", "Mechanical Engineer"),
    ("konstrukteur-maschinenbau", "Konstrukteur Maschinenbau"),
    ("maschinenbau-konstrukteur", "Maschinenbau Konstrukteur"),
    ("entwicklungsingenieur", "Entwicklungsingenieur"),
    ("mechanical-design-engineer", "Mechanical Design Engineer"),
)


@dataclass(frozen=True, slots=True)
class JobsAtSearch:
    slug: str
    label: str


@dataclass(frozen=True, slots=True)
class JobsAtSearchHit:
    job_id: str
    title: str
    url: str


class _SearchLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._job_id: str | None = None
        self._href: str | None = None
        self._parts: list[str] = []
        self.hits: dict[str, JobsAtSearchHit] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or self._job_id is not None:
            return
        href = dict(attrs).get("href")
        if not href:
            return
        match = _JOB_PATH_RE.search(href)
        if not match:
            return
        self._job_id = match.group(1)
        self._href = href
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._job_id is not None and data.strip():
            self._parts.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._job_id is None:
            return
        title = _WS_RE.sub(" ", " ".join(self._parts)).strip()
        if title:
            hit = JobsAtSearchHit(
                job_id=self._job_id,
                title=html.unescape(title),
                url=urljoin(BASE_URL, self._href or f"/i/{self._job_id}"),
            )
            existing = self.hits.get(self._job_id)
            if existing is None or len(hit.title) > len(existing.title):
                self.hits[self._job_id] = hit
        self._job_id = None
        self._href = None
        self._parts = []


class _DetailPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._script_depth = 0
        self._script_parts: list[str] = []
        self._title_depth = 0
        self._title_parts: list[str] = []
        self._h1_depth = 0
        self._h1_parts: list[str] = []
        self.json_ld: list[str] = []
        self.page_title: str | None = None
        self.h1_values: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value for key, value in attrs}
        if tag == "script" and str(attributes.get("type") or "").casefold() == "application/ld+json":
            self._script_depth += 1
            self._script_parts = []
        elif tag == "title":
            self._title_depth += 1
            self._title_parts = []
        elif tag == "h1":
            self._h1_depth += 1
            self._h1_parts = []

    def handle_data(self, data: str) -> None:
        if self._script_depth:
            self._script_parts.append(data)
            return
        if self._title_depth:
            self._title_parts.append(data)
        if self._h1_depth:
            self._h1_parts.append(data)
        cleaned = _WS_RE.sub(" ", data).strip()
        if cleaned:
            self.text_parts.append(cleaned)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script_depth:
            payload = "".join(self._script_parts).strip()
            if payload:
                self.json_ld.append(payload)
            self._script_depth = 0
            self._script_parts = []
        elif tag == "title" and self._title_depth:
            title = _WS_RE.sub(" ", " ".join(self._title_parts)).strip()
            self.page_title = html.unescape(title) or None
            self._title_depth = 0
            self._title_parts = []
        elif tag == "h1" and self._h1_depth:
            value = _WS_RE.sub(" ", " ".join(self._h1_parts)).strip()
            if value:
                self.h1_values.append(html.unescape(value))
            self._h1_depth = 0
            self._h1_parts = []


class _HtmlTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = _WS_RE.sub(" ", data).strip()
        if cleaned:
            self.parts.append(cleaned)


def _html_to_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parser = _HtmlTextParser()
    parser.feed(value)
    text = "\n".join(parser.parts).strip()
    return html.unescape(text) or None


def parse_jobs_at_search_page(content: str) -> tuple[list[JobsAtSearchHit], int | None]:
    parser = _SearchLinkParser()
    parser.feed(content)
    plain = _html_to_text(content) or ""
    match = _RESULT_COUNT_RE.search(plain)
    reported: int | None = None
    if match:
        try:
            reported = int(re.sub(r"[.\s]", "", match.group(1)))
        except ValueError:
            reported = None
    return list(parser.hits.values()), reported


def title_worth_detail(title: str) -> bool:
    return bool(_DETAIL_WORTHY_RE.search(title)) and not bool(_DETAIL_SKIP_RE.search(title))


def _walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _job_posting_from_scripts(scripts: list[str]) -> dict[str, Any] | None:
    for script in scripts:
        try:
            payload = json.loads(script)
        except json.JSONDecodeError:
            continue
        for candidate in _walk_json(payload):
            item_type = candidate.get("@type")
            if item_type == "JobPosting" or (
                isinstance(item_type, list) and "JobPosting" in item_type
            ):
                return candidate
    return None


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _salary_fields(job: dict[str, Any]) -> tuple[
    Decimal | None,
    Decimal | None,
    str | None,
    str | None,
    bool | None,
]:
    salary = job.get("baseSalary")
    if not isinstance(salary, dict):
        return None, None, None, None, None
    currency = salary.get("currency")
    currency_text = currency.strip().upper() if isinstance(currency, str) and currency.strip() else None
    value = salary.get("value")
    if isinstance(value, dict):
        minimum = _as_decimal(value.get("minValue"))
        maximum = _as_decimal(value.get("maxValue"))
        scalar = _as_decimal(value.get("value"))
        if minimum is None and maximum is None and scalar is not None:
            minimum = scalar
        unit = value.get("unitText")
    else:
        minimum = _as_decimal(value)
        maximum = None
        unit = None
    period = str(unit).casefold() if isinstance(unit, str) and unit.strip() else None
    normalized_period = {
        "year": "year",
        "month": "month",
        "week": "week",
        "day": "day",
        "hour": "hour",
    }.get(period or "")
    minimum_only = True if minimum is not None and maximum is None else None
    return minimum, maximum, currency_text, normalized_period, minimum_only


def _location_from_address(address: dict[str, Any], *, remote: bool) -> RawJobLocation | None:
    postal = address.get("postalCode")
    city = address.get("addressLocality")
    region = address.get("addressRegion")
    country = address.get("addressCountry")
    postal_code = str(postal).strip() if postal is not None and str(postal).strip() else None
    city_text = str(city).strip() if city is not None and str(city).strip() else None
    region_text = str(region).strip() if region is not None and str(region).strip() else None
    if isinstance(country, dict):
        country = country.get("name") or country.get("@id")
    country_text = str(country).strip() if country is not None and str(country).strip() else None
    parts = [part for part in (postal_code, city_text, region_text, country_text) if part]
    if not parts:
        return None
    return RawJobLocation(
        postal_code=postal_code,
        city=city_text,
        location_text=", ".join(parts),
        remote=remote,
    )


def _visible_header_location(parts: list[str], *, remote: bool) -> RawJobLocation | None:
    for part in parts[:100]:
        if " - " not in part:
            continue
        left, right = part.rsplit(" - ", 1)
        if not _VISIBLE_AGE_RE.match(right.strip()):
            continue
        location_text = left.strip()
        if not location_text:
            continue
        first = location_text.split(",", 1)[0].strip()
        match = _POSTAL_CITY_RE.match(first)
        postal_code = match.group("postal") if match else None
        city = match.group("city").strip() if match else first
        return RawJobLocation(
            postal_code=postal_code,
            city=city or None,
            location_text=location_text,
            remote=remote,
        )
    return None


def _locations(job: dict[str, Any], parts: list[str]) -> list[RawJobLocation]:
    remote = str(job.get("jobLocationType") or "").casefold() == "telecommute" or any(
        "homeoffice" in part.casefold() for part in parts[:120]
    )
    raw_locations = job.get("jobLocation")
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    if not isinstance(raw_locations, list):
        raw_locations = []
    locations: list[RawJobLocation] = []
    seen: set[tuple[str | None, str | None, str | None, bool]] = set()
    for raw in raw_locations:
        if not isinstance(raw, dict):
            continue
        address = raw.get("address")
        if not isinstance(address, dict):
            address = raw if any(key in raw for key in ("postalCode", "addressLocality")) else None
        if not isinstance(address, dict):
            continue
        location = _location_from_address(address, remote=remote)
        if location is None:
            continue
        key = (location.postal_code, location.city, location.location_text, location.remote)
        if key not in seen:
            seen.add(key)
            locations.append(location)
    if locations:
        return locations
    visible = _visible_header_location(parts, remote=remote)
    return [visible] if visible is not None else []


def _visible_description(parts: list[str], title: str) -> str | None:
    start: int | None = None
    for index, part in enumerate(parts):
        if part.strip() == title.strip():
            start = index + 1
            break
    if start is None:
        return None
    collected: list[str] = []
    for part in parts[start : start + 180]:
        folded = part.casefold()
        if folded in {"ähnliche jobs", "jetzt bewerben"} and collected:
            break
        collected.append(part)
    text = "\n".join(collected).strip()
    return text or None


def _company_from_page_title(page_title: str | None) -> str | None:
    if not page_title:
        return None
    match = re.search(r"\sbei\s(.+?)\s*-\s*jobs\.at\s*$", page_title, re.IGNORECASE)
    return html.unescape(match.group(1).strip()) if match else None


def parse_jobs_at_detail_page(
    content: str,
    *,
    job_id: str,
    url: str,
    search_title: str,
    search_label: str,
) -> RawJob:
    parser = _DetailPageParser()
    parser.feed(content)
    posting = _job_posting_from_scripts(parser.json_ld) or {}

    title = posting.get("title")
    if not isinstance(title, str) or not title.strip():
        title = parser.h1_values[0] if parser.h1_values else search_title
    title = html.unescape(title.strip())

    company: str | None = None
    organization = posting.get("hiringOrganization")
    if isinstance(organization, dict):
        value = organization.get("name")
        if isinstance(value, str) and value.strip():
            company = value.strip()
    if company is None:
        company = _company_from_page_title(parser.page_title)

    description = _html_to_text(posting.get("description")) or _visible_description(
        parser.text_parts,
        title,
    )
    salary_min, salary_max, currency, salary_period, minimum_only = _salary_fields(posting)
    salary_text: str | None = None
    if salary_min is None and salary_max is None:
        for part in parser.text_parts[:140]:
            match = _VISIBLE_SALARY_RE.search(part)
            if match:
                salary_text = match.group("salary")
                break
    locations = _locations(posting, parser.text_parts)

    canonical_url = posting.get("url")
    if not isinstance(canonical_url, str) or not canonical_url.startswith("https://"):
        canonical_url = url

    raw_payload: dict[str, Any] = {
        "wohnwerk_board": "jobs.at",
        "jobs_at_job_id": job_id,
        "jobs_at_search_label": search_label,
        "jobs_at_search_title": search_title,
        "date_posted": posting.get("datePosted"),
        "valid_through": posting.get("validThrough"),
        "employment_type": posting.get("employmentType"),
        "job_location_type": posting.get("jobLocationType"),
        "detail_schema": "schema.org/JobPosting" if posting else "visible-page-fallback",
    }

    structured_salary = salary_min is not None or salary_max is not None
    return RawJob(
        source_listing_id=f"jobsat:{job_id}",
        url=canonical_url,
        title=title,
        company=company,
        description=description,
        salary_text=salary_text,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        salary_period=salary_period,
        salary_payment_count=None,
        salary_provenance="EXPLICIT" if structured_salary else None,
        salary_confidence=Decimal(1) if structured_salary else None,
        salary_is_minimum_only=minimum_only,
        locations=locations,
        raw_payload=raw_payload,
    )


class JobsAtJobSource(JobSource):
    """Low-impact jobs.at search frontier with title-gated detail requests."""

    name = "jobs.at"

    def __init__(
        self,
        *,
        searches: list[JobsAtSearch] | None = None,
        request_delay_seconds: float = 0.75,
        max_details_per_shard: int = 8,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.searches = searches or [JobsAtSearch(*row) for row in _DEFAULT_SEARCHES]
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.max_details_per_shard = max(1, max_details_per_shard)
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
            now = time.monotonic()
            remaining = self.request_delay_seconds - (now - self._last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_request_at = time.monotonic()

    async def _request_text(self, client: httpx.AsyncClient, url: str) -> str:
        await self._rate_limit()
        response = await client.get(url)
        if response.status_code == 429:
            raise httpx.HTTPStatusError(
                "jobs.at rate limited the low-impact collector",
                request=response.request,
                response=response,
            )
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
            raise TypeError(f"Invalid jobs.at shard params: {shard.params!r}")

        search_url = f"{BASE_URL}/j/{slug}"
        pages_fetched = 0
        items: list[RawJob] = []
        search_hits = 0
        detail_candidates = 0
        skipped_duplicate = 0
        skipped_title = 0

        headers = {
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian job search; low-rate public scan)",
        }

        async with httpx.AsyncClient(
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            try:
                search_html = await self._request_text(client, search_url)
                pages_fetched += 1
                hits, reported_count = parse_jobs_at_search_page(search_html)
                search_hits = len(hits)

                for hit in hits:
                    if hit.job_id in self._seen_ids:
                        skipped_duplicate += 1
                        continue
                    self._seen_ids.add(hit.job_id)
                    if not title_worth_detail(hit.title):
                        skipped_title += 1
                        continue
                    detail_candidates += 1
                    if len(items) >= self.max_details_per_shard:
                        continue
                    job = self._detail_cache.get(hit.job_id)
                    if job is None:
                        detail_html = await self._request_text(client, hit.url)
                        pages_fetched += 1
                        job = parse_jobs_at_detail_page(
                            detail_html,
                            job_id=hit.job_id,
                            url=hit.url,
                            search_title=hit.title,
                            search_label=label,
                        )
                        self._detail_cache[hit.job_id] = job
                    items.append(job)

                return SourceBatch(
                    items=items,
                    next_cursor={
                        "strategy": "first-page-title-frontier",
                        "search_url": search_url,
                        "search_reported_count": reported_count,
                        "search_hits": search_hits,
                        "detail_candidates": detail_candidates,
                        "details_fetched": len(items),
                        "skipped_duplicate": skipped_duplicate,
                        "skipped_title": skipped_title,
                        "max_details_per_shard": self.max_details_per_shard,
                    },
                    source_reported_count=reported_count,
                    coverage_complete=False,
                    result_cap_hit=False,
                    pages_fetched=pages_fetched,
                )
            except Exception as exc:
                raise SourceFetchError(
                    f"jobs.at shard {shard.key!r} failed after {pages_fetched} requests: {exc}",
                    pages_fetched=pages_fetched,
                    items_seen=len(items),
                    source_reported_count=None,
                    next_cursor={
                        "strategy": "first-page-title-frontier",
                        "search_url": search_url,
                        "search_hits": search_hits,
                        "detail_candidates": detail_candidates,
                        "details_fetched": len(items),
                    },
                    partial_items=items,
                ) from exc
