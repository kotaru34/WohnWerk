from __future__ import annotations

import asyncio
import html
import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from app.jobs.location_postal_evidence import explicit_postal_for_locality
from app.sources.base import (
    JobSource,
    RawJob,
    RawJobLocation,
    SourceBatch,
    SourceFetchError,
    SourceShardSpec,
)

BASE_URL = "https://www.karriere.at"

_JOB_PATH_RE = re.compile(r"(?:https?://(?:www\.)?karriere\.at)?/jobs/(\d+)(?:[/?#]|$)")
_WS_RE = re.compile(r"\s+")
_RESULT_COUNT_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*|\d+)\s+[^\n]{0,80}?Jobs\b",
    re.IGNORECASE,
)
_DETAIL_WORTHY_RE = re.compile(
    r"(?:konstruk|maschinenbau|mechanical|cad|entwicklungsingenieur|"
    r"development\s+engineer|design\s+engineer|project\s+engineer|projektingenieur|"
    r"technisch\w*\s+projekt|projektleiter|sondermaschinen|fahrzeug|automotive|"
    r"berechnungsingenieur|simulation\s+engineer|product\s+engineer|"
    r"mechanik|baugruppen|antrieb|chassis)",
    re.IGNORECASE,
)
_DETAIL_SKIP_RE = re.compile(
    r"(?:elektro|electrical|eplan|software|full[-\s]*stack|data\s+(?:engineer|scientist)|"
    r"sales|vertrieb|lehr(?:e|ausbildung)|trainee|internship|werkstudent|"
    r"kfz[-/\s]*(?:mechaniker|techniker|mechatroniker))",
    re.IGNORECASE,
)

_DEFAULT_SEARCHES = (
    ("konstrukteur-maschinenbau", "Konstrukteur Maschinenbau"),
    ("mechanischer-konstrukteur", "Mechanischer Konstrukteur"),
    ("konstrukteur-sondermaschinenbau", "Konstrukteur Sondermaschinenbau"),
    ("mechanical-design-engineer", "Mechanical Design Engineer"),
    ("entwicklungsingenieur", "Entwicklungsingenieur"),
)


@dataclass(frozen=True, slots=True)
class KarriereSearch:
    slug: str
    label: str


@dataclass(frozen=True, slots=True)
class KarriereSearchHit:
    job_id: str
    title: str
    url: str


class _SearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.job_id: str | None = None
        self.href: str | None = None
        self.parts: list[str] = []
        self.hits: dict[str, KarriereSearchHit] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or self.job_id is not None:
            return
        href = dict(attrs).get("href")
        if not href or not (match := _JOB_PATH_RE.search(href)):
            return
        self.job_id = match.group(1)
        self.href = href
        self.parts = []

    def handle_data(self, data: str) -> None:
        if self.job_id is not None and data.strip():
            self.parts.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self.job_id is None:
            return
        title = html.unescape(_WS_RE.sub(" ", " ".join(self.parts)).strip())
        if title:
            hit = KarriereSearchHit(
                job_id=self.job_id,
                title=title,
                url=urljoin(BASE_URL, self.href or f"/jobs/{self.job_id}"),
            )
            old = self.hits.get(self.job_id)
            if old is None or len(hit.title) > len(old.title):
                self.hits[self.job_id] = hit
        self.job_id = None
        self.href = None
        self.parts = []


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_json = False
        self.in_title = False
        self.buffer: list[str] = []
        self.json_ld: list[str] = []
        self.page_title: str | None = None
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.casefold(): value for key, value in attrs}
        if tag == "script" and str(values.get("type") or "").casefold() == "application/ld+json":
            self.in_json = True
            self.buffer = []
        elif tag == "title":
            self.in_title = True
            self.buffer = []

    def handle_data(self, data: str) -> None:
        if self.in_json:
            self.buffer.append(data)
            return
        if self.in_title:
            self.buffer.append(data)
        value = _WS_RE.sub(" ", data).strip()
        if value:
            self.text_parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_json:
            value = "".join(self.buffer).strip()
            if value:
                self.json_ld.append(value)
            self.in_json = False
            self.buffer = []
        elif tag == "title" and self.in_title:
            value = _WS_RE.sub(" ", " ".join(self.buffer)).strip()
            self.page_title = html.unescape(value) or None
            self.in_title = False
            self.buffer = []


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = _WS_RE.sub(" ", data).strip()
        if value:
            self.parts.append(value)


def _html_to_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parser = _TextParser()
    parser.feed(value)
    return html.unescape("\n".join(parser.parts).strip()) or None


def parse_karriere_search_page(content: str) -> tuple[list[KarriereSearchHit], int | None]:
    parser = _SearchParser()
    parser.feed(content)
    match = _RESULT_COUNT_RE.search(_html_to_text(content) or "")
    reported = int(re.sub(r"[.\s]", "", match.group(1))) if match else None
    return list(parser.hits.values()), reported


def title_worth_detail(title: str) -> bool:
    return bool(_DETAIL_WORTHY_RE.search(title)) and not bool(_DETAIL_SKIP_RE.search(title))


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _job_posting(scripts: list[str]) -> dict[str, Any]:
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
    return {}


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _salary(job: dict[str, Any]) -> tuple[
    Decimal | None,
    Decimal | None,
    str | None,
    str | None,
    bool | None,
]:
    raw = job.get("baseSalary")
    if not isinstance(raw, dict):
        return None, None, None, None, None
    currency = raw.get("currency")
    currency = currency.upper() if isinstance(currency, str) and currency.strip() else None
    value = raw.get("value")
    if isinstance(value, dict):
        minimum = _decimal(value.get("minValue"))
        maximum = _decimal(value.get("maxValue"))
        scalar = _decimal(value.get("value"))
        if minimum is None and maximum is None:
            minimum = scalar
        unit = value.get("unitText")
    else:
        minimum, maximum, unit = _decimal(value), None, None
    period = str(unit).casefold() if isinstance(unit, str) else ""
    period = {
        "year": "year",
        "month": "month",
        "week": "week",
        "day": "day",
        "hour": "hour",
    }.get(period)
    minimum_only = True if minimum is not None and maximum is None else None
    return minimum, maximum, currency, period, minimum_only


def _address_location(address: dict[str, Any], *, remote: bool) -> RawJobLocation | None:
    postal = address.get("postalCode")
    city = address.get("addressLocality")
    region = address.get("addressRegion")
    country = address.get("addressCountry")
    postal_text = str(postal).strip() if postal is not None and str(postal).strip() else None
    city_text = str(city).strip() if city is not None and str(city).strip() else None
    region_text = str(region).strip() if region is not None and str(region).strip() else None
    if isinstance(country, dict):
        country = country.get("name") or country.get("@id")
    country_text = str(country).strip() if country else None
    parts = [value for value in (postal_text, city_text, region_text, country_text) if value]
    if not parts:
        return None
    return RawJobLocation(
        postal_code=postal_text,
        city=city_text,
        location_text=", ".join(parts),
        remote=remote,
    )


def _with_visible_postal(location: RawJobLocation, content: str) -> RawJobLocation:
    if location.postal_code is not None or not location.city:
        return location
    postal = explicit_postal_for_locality(content, location.city)
    if postal is None:
        return location
    return RawJobLocation(
        postal_code=postal,
        city=location.city,
        location_text=location.location_text,
        remote=location.remote,
    )


def _locations(job: dict[str, Any], page_text: list[str], content: str) -> list[RawJobLocation]:
    remote = str(job.get("jobLocationType") or "").casefold() == "telecommute"
    raw = job.get("jobLocation")
    raw = [raw] if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    result: list[RawJobLocation] = []
    seen: set[tuple[str | None, str | None, str | None, bool]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        address = item.get("address")
        if not isinstance(address, dict):
            address = item if "addressLocality" in item or "postalCode" in item else None
        if not isinstance(address, dict):
            continue
        location = _address_location(address, remote=remote)
        if location is None:
            continue
        location = _with_visible_postal(location, content)
        key = (location.postal_code, location.city, location.location_text, location.remote)
        if key not in seen:
            seen.add(key)
            result.append(location)
    if result:
        return result
    for index, value in enumerate(page_text[:-1]):
        if value.casefold() == "dienstort":
            city = page_text[index + 1].strip()
            if city:
                location = RawJobLocation(city=city, location_text=city, remote=remote)
                return [_with_visible_postal(location, content)]
    return []


def parse_karriere_detail_page(
    content: str,
    *,
    job_id: str,
    url: str,
    search_title: str,
    search_label: str,
) -> RawJob:
    parser = _PageParser()
    parser.feed(content)
    posting = _job_posting(parser.json_ld)
    title = posting.get("title")
    title = title.strip() if isinstance(title, str) and title.strip() else search_title

    company: str | None = None
    organization = posting.get("hiringOrganization")
    if isinstance(organization, dict):
        name = organization.get("name")
        company = name.strip() if isinstance(name, str) and name.strip() else None
    if company is None and parser.page_title:
        match = re.search(
            r"\sbei\s(.+?)\s*\|\s*karriere\.at\s*$",
            parser.page_title,
            re.IGNORECASE,
        )
        company = html.unescape(match.group(1).strip()) if match else None

    salary_min, salary_max, currency, period, minimum_only = _salary(posting)
    canonical_url = posting.get("url")
    if not isinstance(canonical_url, str) or not canonical_url.startswith("https://"):
        canonical_url = url

    return RawJob(
        source_listing_id=f"karriere:{job_id}",
        url=canonical_url,
        title=title,
        company=company,
        description=_html_to_text(posting.get("description")),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=currency,
        salary_period=period,
        salary_payment_count=None,
        salary_provenance="EXPLICIT" if salary_min is not None or salary_max is not None else None,
        salary_confidence=Decimal(1) if salary_min is not None or salary_max is not None else None,
        salary_is_minimum_only=minimum_only,
        locations=_locations(posting, parser.text_parts, content),
        raw_payload={
            "wohnwerk_board": "karriere.at",
            "karriere_job_id": job_id,
            "karriere_search_label": search_label,
            "karriere_search_title": search_title,
            "date_posted": posting.get("datePosted"),
            "valid_through": posting.get("validThrough"),
            "employment_type": posting.get("employmentType"),
            "job_location_type": posting.get("jobLocationType"),
            "direct_apply": posting.get("directApply"),
            "detail_schema": "schema.org/JobPosting" if posting else "visible-page-fallback",
        },
    )


class KarriereAtJobSource(JobSource):
    """Polite first-page search frontier with title-gated detail requests."""

    name = "karriere.at"

    def __init__(
        self,
        *,
        searches: list[KarriereSearch] | None = None,
        request_delay_seconds: float = 0.65,
        max_details_per_shard: int = 8,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.searches = searches or [KarriereSearch(*row) for row in _DEFAULT_SEARCHES]
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.max_details_per_shard = max(1, max_details_per_shard)
        self.transport = transport
        self._lock = asyncio.Lock()
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
        async with self._lock:
            remaining = self.request_delay_seconds - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_request_at = time.monotonic()

    async def _request(self, client: httpx.AsyncClient, url: str) -> str:
        await self._rate_limit()
        response = await client.get(url)
        if response.status_code == 429:
            raise httpx.HTTPStatusError(
                "karriere.at rate limited the collector",
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
            raise TypeError(f"Invalid karriere.at shard params: {shard.params!r}")

        search_url = f"{BASE_URL}/jobs/{slug}"
        pages = 0
        items: list[RawJob] = []
        hits_count = 0
        candidates = 0
        duplicates = 0
        skipped = 0
        reported: int | None = None
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
                search_html = await self._request(client, search_url)
                pages += 1
                hits, reported = parse_karriere_search_page(search_html)
                hits_count = len(hits)
                for hit in hits:
                    if hit.job_id in self._seen_ids:
                        duplicates += 1
                        continue
                    self._seen_ids.add(hit.job_id)
                    if not title_worth_detail(hit.title):
                        skipped += 1
                        continue
                    candidates += 1
                    if len(items) >= self.max_details_per_shard:
                        continue
                    job = self._detail_cache.get(hit.job_id)
                    if job is None:
                        detail_html = await self._request(client, hit.url)
                        pages += 1
                        job = parse_karriere_detail_page(
                            detail_html,
                            job_id=hit.job_id,
                            url=hit.url,
                            search_title=hit.title,
                            search_label=label,
                        )
                        self._detail_cache[hit.job_id] = job
                    items.append(job)
            except Exception as exc:
                raise SourceFetchError(
                    f"karriere.at shard {shard.key!r} failed after {pages} requests: {exc}",
                    pages_fetched=pages,
                    items_seen=len(items),
                    source_reported_count=reported,
                    partial_items=items,
                    next_cursor={"strategy": "first-page-title-frontier", "search_url": search_url},
                ) from exc

        return SourceBatch(
            items=items,
            next_cursor={
                "strategy": "first-page-title-frontier",
                "search_url": search_url,
                "search_reported_count": reported,
                "search_hits": hits_count,
                "detail_candidates": candidates,
                "details_fetched": len(items),
                "skipped_duplicate": duplicates,
                "skipped_title": skipped,
                "max_details_per_shard": self.max_details_per_shard,
            },
            source_reported_count=reported,
            coverage_complete=False,
            result_cap_hit=False,
            pages_fetched=pages,
        )
