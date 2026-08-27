from __future__ import annotations

import asyncio
import html
import math
import re
from dataclasses import dataclass
from html.parser import HTMLParser
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

SMARTRECRUITERS_API_BASE = "https://api.smartrecruiters.com/v1/companies"
_SMARTRECRUITERS_JOBS_BASE = "https://jobs.smartrecruiters.com"
_SPACE_RE = re.compile(r"\s+")
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True, slots=True)
class SmartRecruitersSite:
    tenant: str
    company: str

    def __post_init__(self) -> None:
        if not self.tenant.strip():
            raise ValueError("SmartRecruiters tenant must not be empty")
        if not self.company.strip():
            raise ValueError("SmartRecruiters company must not be empty")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _html_to_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parser = _TextExtractor()
    parser.feed(value)
    normalized = _SPACE_RE.sub(" ", " ".join(parser.parts)).strip()
    return html.unescape(normalized) or None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _label(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    return _text(value.get("label"))


def _is_austria_country(value: object) -> bool:
    country = (_text(value) or "").casefold()
    return country in {"at", "austria", "österreich", "oesterreich"}


def _description(payload: dict[str, Any]) -> str | None:
    """Return job-specific text while excluding generic company boilerplate."""
    job_ad = payload.get("jobAd")
    if not isinstance(job_ad, dict):
        return None
    sections = job_ad.get("sections")
    if not isinstance(sections, dict):
        return None

    parts: list[str] = []
    for key in ("jobDescription", "qualifications", "additionalInformation"):
        section = sections.get(key)
        if not isinstance(section, dict):
            continue
        title = _html_to_text(section.get("title"))
        body = _html_to_text(section.get("text"))
        text = "\n".join(part for part in (title, body) if part)
        if text:
            parts.append(text)
    return "\n\n".join(parts) or None


def _location(payload: dict[str, Any]) -> RawJobLocation | None:
    value = payload.get("location")
    if not isinstance(value, dict) or not _is_austria_country(value.get("country")):
        return None

    city = _text(value.get("city"))
    region = _text(value.get("region"))
    remote = bool(value.get("remote"))
    location_parts = [part for part in (city, region, "Austria") if part]
    location_text = ", ".join(dict.fromkeys(location_parts)) or "Austria"
    return RawJobLocation(
        city=city,
        location_text=location_text,
        remote=remote,
    )


def parse_smartrecruiters_detail(
    payload: dict[str, Any],
    *,
    site: SmartRecruitersSite,
) -> RawJob | None:
    posting_id = _text(payload.get("id")) or _text(payload.get("uuid"))
    title = _text(payload.get("name"))
    if posting_id is None:
        raise ValueError(f"SmartRecruiters tenant {site.tenant!r} returned detail without id")
    if title is None:
        raise ValueError(
            f"SmartRecruiters tenant {site.tenant!r} returned posting {posting_id!r} without title"
        )

    location = _location(payload)
    if location is None:
        return None

    company_obj = payload.get("company")
    company = site.company
    if isinstance(company_obj, dict):
        company = _text(company_obj.get("name")) or company

    posting_url = _text(payload.get("postingUrl"))
    if posting_url is None:
        posting_url = f"{_SMARTRECRUITERS_JOBS_BASE}/{site.tenant}/{posting_id}"

    raw_payload = {
        "wohnwerk_smartrecruiters_tenant": site.tenant,
        "wohnwerk_company": company,
        "smartrecruiters_uuid": _text(payload.get("uuid")),
        "smartrecruiters_job_id": _text(payload.get("jobId")),
        "smartrecruiters_job_ad_id": _text(payload.get("jobAdId")),
        "smartrecruiters_ref_number": _text(payload.get("refNumber")),
        "smartrecruiters_released_date": _text(payload.get("releasedDate")),
        "smartrecruiters_department": _label(payload.get("department")),
        "smartrecruiters_function": _label(payload.get("function")),
        "smartrecruiters_industry": _label(payload.get("industry")),
        "smartrecruiters_employment_type": _label(payload.get("typeOfEmployment")),
        "smartrecruiters_experience_level": _label(payload.get("experienceLevel")),
        "smartrecruiters_apply_url": _text(payload.get("applyUrl")),
        "smartrecruiters_location": dict(payload.get("location") or {}),
        "smartrecruiters_custom_fields": payload.get("customField") or [],
    }

    return RawJob(
        source_listing_id=f"{site.tenant}:{posting_id}",
        url=posting_url,
        title=title,
        company=company,
        description=_description(payload),
        locations=[location],
        raw_payload=raw_payload,
    )


def parse_smartrecruiters_list(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    content = payload.get("content")
    total = payload.get("totalFound")
    if not isinstance(content, list):
        raise TypeError("SmartRecruiters posting list has no content array")
    if not isinstance(total, int) or total < 0:
        raise ValueError("SmartRecruiters posting list has invalid totalFound")

    rows: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            raise TypeError("SmartRecruiters posting list contains a non-object item")
        rows.append(item)
    return rows, total


class SmartRecruitersJobSource(JobSource):
    """Public SmartRecruiters Posting API, restricted to Austrian public jobs."""

    name = "smartrecruiters-public-postings"

    def __init__(
        self,
        *,
        sites: list[SmartRecruitersSite],
        request_delay_seconds: float = 0.2,
        incremental_pages: int = 1,
        hard_max_pages: int = 100,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not sites:
            raise ValueError("At least one SmartRecruiters tenant is required")
        self.sites = list(sites)
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.incremental_pages = max(1, incremental_pages)
        self.hard_max_pages = max(1, hard_max_pages)
        self.timeout_seconds = timeout_seconds

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=site.tenant,
                params={"tenant": site.tenant, "company": site.company},
            )
            for site in self.sites
        ]

    @staticmethod
    def _site_from_shard(shard: SourceShardSpec) -> SmartRecruitersSite:
        tenant = shard.params.get("tenant")
        company = shard.params.get("company")
        if not isinstance(tenant, str) or not isinstance(company, str):
            raise TypeError(f"Invalid SmartRecruiters shard parameters for {shard.key!r}")
        return SmartRecruitersSite(tenant=tenant, company=company)

    async def _sleep(self) -> None:
        if self.request_delay_seconds > 0:
            await asyncio.sleep(self.request_delay_seconds)

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(3):
            await self._sleep()
            try:
                response = await client.get(url, params=params)
                if response.status_code in _RETRYABLE_STATUS:
                    response.raise_for_status()
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise TypeError("SmartRecruiters returned a non-object JSON response")
                return payload
            except (httpx.HTTPError, TypeError, ValueError) as exc:
                last_error = exc
                retryable = isinstance(exc, httpx.HTTPStatusError) and (
                    exc.response.status_code in _RETRYABLE_STATUS
                )
                if attempt == 2 or (isinstance(exc, httpx.HTTPStatusError) and not retryable):
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
        del cursor
        site = self._site_from_shard(shard)
        list_url = f"{SMARTRECRUITERS_API_BASE}/{site.tenant}/postings"
        headers = {
            "Accept": "application/json",
            "Accept-Language": "de-AT,de;q=0.9,en;q=0.7",
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian job search)",
        }

        page_size = 100
        pages_fetched = 0
        source_reported: int | None = None
        max_pages = 1
        result_cap_hit = False
        detail_attempted = 0
        detail_succeeded = 0
        detail_failed = 0
        detail_failed_ids: list[str] = []
        items_by_id: dict[str, RawJob] = {}

        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout_seconds,
            follow_redirects=True,
        ) as client:
            page_number = 0
            while True:
                if page_number >= self.hard_max_pages:
                    result_cap_hit = True
                    break
                if not reconciliation and page_number >= self.incremental_pages:
                    break
                if page_number >= max_pages:
                    break

                try:
                    payload = await self._get_json(
                        client,
                        list_url,
                        params={
                            "country": "at",
                            "destination": "PUBLIC",
                            "limit": page_size,
                            "offset": page_number * page_size,
                        },
                    )
                    rows, total_found = parse_smartrecruiters_list(payload)
                except (httpx.HTTPError, TypeError, ValueError) as exc:
                    raise SourceFetchError(
                        f"SmartRecruiters shard {shard.key!r} list fetch failed: {exc}",
                        pages_fetched=pages_fetched,
                        items_seen=len(items_by_id),
                        source_reported_count=source_reported,
                        next_cursor={
                            "source_postings": source_reported,
                            "detail_attempted": detail_attempted,
                            "detail_succeeded": detail_succeeded,
                            "detail_failed": detail_failed,
                            "detail_failed_ids": detail_failed_ids[:20],
                        },
                        partial_items=list(items_by_id.values()),
                    ) from exc

                pages_fetched += 1
                source_reported = total_found
                max_pages = max(1, math.ceil(total_found / page_size))
                if max_pages > self.hard_max_pages:
                    result_cap_hit = True

                for row in rows:
                    posting_id = _text(row.get("id")) or _text(row.get("uuid"))
                    if posting_id is None:
                        detail_failed += 1
                        detail_failed_ids.append("<missing-id>")
                        continue

                    detail_attempted += 1
                    detail_url = f"{list_url}/{posting_id}"
                    try:
                        detail = await self._get_json(client, detail_url)
                        job = parse_smartrecruiters_detail(detail, site=site)
                    except (httpx.HTTPError, TypeError, ValueError):
                        detail_failed += 1
                        detail_failed_ids.append(posting_id)
                        continue
                    if job is None:
                        detail_failed += 1
                        detail_failed_ids.append(posting_id)
                        continue
                    items_by_id[job.source_listing_id] = job
                    detail_succeeded += 1

                page_number += 1
                if page_number >= max_pages:
                    break

        coverage_complete = (
            reconciliation
            and not result_cap_hit
            and pages_fetched == max_pages
            and detail_failed == 0
        )

        return SourceBatch(
            items=list(items_by_id.values()),
            next_cursor={
                "source_postings": source_reported,
                "source_pages": max_pages,
                "detail_attempted": detail_attempted,
                "detail_succeeded": detail_succeeded,
                "detail_failed": detail_failed,
                "detail_failed_ids": detail_failed_ids[:20],
            },
            source_reported_count=source_reported,
            coverage_complete=coverage_complete,
            result_cap_hit=result_cap_hit,
            pages_fetched=pages_fetched,
        )
