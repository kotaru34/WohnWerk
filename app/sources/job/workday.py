from __future__ import annotations

import asyncio
import html
import math
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from app.jobs.identity import workday_requisition_identity, with_stable_identity
from app.jobs.location_resolution import canonicalize_locality
from app.sources.base import (
    JobSource,
    RawJob,
    RawJobLocation,
    SourceBatch,
    SourceFetchError,
    SourceShardSpec,
)

_WORKDAY_PAGE_SIZE = 20
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_SPACE_RE = re.compile(r"\s+")
_MULTI_LOCATION_PLACEHOLDER_RE = re.compile(r"^\d+\s+locations?$", re.IGNORECASE)
_AT_TOKEN_RE = re.compile(r"(?:^|[,;]\s*)AT(?:\s*[,;]|$)", re.IGNORECASE)
_AUSTRIA_RE = re.compile(r"\b(?:austria|österreich|oesterreich)\b", re.IGNORECASE)
_REMOTE_RE = re.compile(r"\b(?:remote|home\s*office|homeoffice)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class WorkdaySite:
    tenant: str
    site: str
    company: str
    origin: str
    search_texts: tuple[str, ...]
    locale: str = "en-US"

    def __post_init__(self) -> None:
        if not self.tenant.strip():
            raise ValueError("Workday tenant must not be empty")
        if not self.site.strip():
            raise ValueError("Workday site must not be empty")
        if not self.company.strip():
            raise ValueError("Workday company must not be empty")
        if not self.origin.startswith("https://"):
            raise ValueError("Workday origin must be an HTTPS origin")
        if not self.search_texts or any(not value.strip() for value in self.search_texts):
            raise ValueError("Workday search_texts must contain non-empty frontier queries")

    @property
    def cxs_base_url(self) -> str:
        return f"{self.origin.rstrip('/')}/wday/cxs/{self.tenant}/{self.site}"

    @property
    def public_base_url(self) -> str:
        return f"{self.origin.rstrip('/')}/{self.locale}/{self.site}"


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
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        stripped = str(value).strip()
        return stripped or None
    return None


def _workday_list(payload: object) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(payload, dict):
        raise TypeError("Workday listing response is not an object")
    postings = payload.get("jobPostings")
    total = payload.get("total")
    if not isinstance(postings, list):
        raise TypeError("Workday listing response has no jobPostings array")
    if not isinstance(total, int) or total < 0:
        raise ValueError("Workday listing response has invalid total")

    rows: list[dict[str, Any]] = []
    for posting in postings:
        if not isinstance(posting, dict):
            raise TypeError("Workday jobPostings contains a non-object item")
        rows.append(posting)
    return rows, total


def _nested_country_code(info: dict[str, Any]) -> str | None:
    requisition_location = info.get("jobRequisitionLocation")
    if not isinstance(requisition_location, dict):
        return None
    country = requisition_location.get("country")
    if not isinstance(country, dict):
        return None
    value = _text(country.get("alpha2Code"))
    return value.upper() if value else None


def _known_city(text: str, austrian_localities: set[str]) -> str | None:
    first = text.split(",", 1)[0].strip()
    if not first or _AUSTRIA_RE.fullmatch(first) or first.casefold() == "at":
        return None
    if _MULTI_LOCATION_PLACEHOLDER_RE.fullmatch(first):
        return None
    canonical = canonicalize_locality(first)
    if canonical is not None and canonical in austrian_localities:
        return first
    return None


def _location_from_text(
    value: object,
    *,
    austrian_localities: set[str],
    country_code_at: bool = False,
) -> RawJobLocation | None:
    text = _text(value)
    if text is None or _MULTI_LOCATION_PLACEHOLDER_RE.fullmatch(text):
        return None

    explicit_austria = bool(_AUSTRIA_RE.search(text) or _AT_TOKEN_RE.search(text))
    city = _known_city(text, austrian_localities)
    if not explicit_austria and not country_code_at and city is None:
        return None

    if city is None and (explicit_austria or country_code_at):
        first = text.split(",", 1)[0].strip()
        if (
            first
            and not _AUSTRIA_RE.fullmatch(first)
            and first.casefold() != "at"
            and not _MULTI_LOCATION_PLACEHOLDER_RE.fullmatch(first)
            and not _REMOTE_RE.fullmatch(first)
        ):
            city = first

    return RawJobLocation(
        city=city,
        location_text=text,
        remote=bool(_REMOTE_RE.search(text)),
    )


def _additional_location_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        candidate = (
            _text(item.get("location"))
            or _text(item.get("descriptor"))
            or _text(item.get("name"))
        )
        if candidate:
            result.append(candidate)
    return result


def _requisition_id(info: dict[str, Any], external_path: str) -> str:
    explicit = _text(info.get("jobReqId")) or _text(info.get("jobPostingId"))
    if explicit:
        return explicit
    leaf = external_path.rstrip("/").rsplit("/", 1)[-1]
    if "_" in leaf:
        suffix = leaf.rsplit("_", 1)[-1].strip()
        if suffix:
            return suffix
    return leaf


def parse_workday_detail(
    payload: object,
    *,
    site: WorkdaySite,
    listing: dict[str, Any],
    austrian_localities: set[str],
) -> RawJob | None:
    if not isinstance(payload, dict):
        raise TypeError("Workday detail response is not an object")
    info = payload.get("jobPostingInfo")
    if not isinstance(info, dict):
        raise TypeError("Workday detail response has no jobPostingInfo object")

    title = _text(info.get("title")) or _text(listing.get("title"))
    external_path = _text(listing.get("externalPath"))
    if title is None or external_path is None:
        raise ValueError("Workday posting is missing title or externalPath")
    if not external_path.startswith("/"):
        external_path = f"/{external_path}"

    country_code = _nested_country_code(info)
    locations: list[RawJobLocation] = []
    primary = _location_from_text(
        info.get("location") or listing.get("locationsText"),
        austrian_localities=austrian_localities,
        country_code_at=country_code == "AT",
    )
    if primary is not None:
        locations.append(primary)

    for location_text in _additional_location_values(info.get("additionalLocations")):
        parsed = _location_from_text(
            location_text,
            austrian_localities=austrian_localities,
        )
        if parsed is None:
            continue
        key = (parsed.city, parsed.location_text, parsed.remote)
        if any((row.city, row.location_text, row.remote) == key for row in locations):
            continue
        locations.append(parsed)

    if not locations:
        return None

    requisition_id = _requisition_id(info, external_path)
    identity = workday_requisition_identity(site.tenant, site.site, requisition_id)
    source_listing_id = f"{site.tenant}:{site.site}:{requisition_id}"
    public_url = urljoin(f"{site.public_base_url}/", external_path.lstrip("/"))
    explicit_url = _text(info.get("externalUrl")) or _text(info.get("jobPostingUrl"))
    if explicit_url and explicit_url.startswith("https://"):
        public_url = explicit_url

    raw_payload = with_stable_identity(
        {
            "wohnwerk_workday_tenant": site.tenant,
            "wohnwerk_workday_site": site.site,
            "wohnwerk_company": site.company,
            "workday_job_req_id": requisition_id,
            "workday_job_posting_id": _text(info.get("jobPostingId")),
            "workday_external_path": external_path,
            "workday_posted_on": _text(listing.get("postedOn")),
            "workday_start_date": _text(info.get("startDate")),
            "workday_time_type": _text(info.get("timeType")),
            "workday_locations_text": _text(listing.get("locationsText")),
            "workday_country_code": country_code,
            "workday_bullet_fields": listing.get("bulletFields") or [],
        },
        identity,
    )

    return RawJob(
        source_listing_id=source_listing_id,
        url=public_url,
        title=title,
        company=site.company,
        description=_html_to_text(info.get("jobDescription")),
        locations=locations,
        raw_payload=raw_payload,
    )


class WorkdayJobSource(JobSource):
    """Public Workday CXS frontier restricted to explicitly Austrian locations."""

    name = "workday-public-cxs"

    def __init__(
        self,
        *,
        sites: list[WorkdaySite],
        austrian_localities: set[str],
        request_delay_seconds: float = 0.15,
        hard_max_pages: int = 25,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not sites:
            raise ValueError("At least one Workday site is required")
        self.sites = list(sites)
        self.austrian_localities = {
            canonical
            for value in austrian_localities
            if (canonical := canonicalize_locality(value)) is not None
        }
        if not self.austrian_localities:
            raise ValueError("Austrian locality reference must not be empty")
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.hard_max_pages = max(1, hard_max_pages)
        self.timeout_seconds = timeout_seconds

    def default_shards(self) -> list[SourceShardSpec]:
        shards: list[SourceShardSpec] = []
        for site in self.sites:
            for index, search_text in enumerate(site.search_texts, start=1):
                shards.append(
                    SourceShardSpec(
                        key=f"{site.tenant}:{site.site}:{index}",
                        params={
                            "tenant": site.tenant,
                            "site": site.site,
                            "company": site.company,
                            "origin": site.origin,
                            "locale": site.locale,
                            "search_text": search_text,
                        },
                    )
                )
        return shards

    @staticmethod
    def _site_from_shard(shard: SourceShardSpec) -> tuple[WorkdaySite, str]:
        params = shard.params
        values = {
            key: params.get(key)
            for key in ("tenant", "site", "company", "origin", "locale", "search_text")
        }
        if not all(isinstance(value, str) and value.strip() for value in values.values()):
            raise TypeError(f"Invalid Workday shard parameters for {shard.key!r}")
        site = WorkdaySite(
            tenant=values["tenant"],
            site=values["site"],
            company=values["company"],
            origin=values["origin"],
            locale=values["locale"],
            search_texts=(values["search_text"],),
        )
        return site, values["search_text"]

    async def _sleep(self) -> None:
        if self.request_delay_seconds > 0:
            await asyncio.sleep(self.request_delay_seconds)

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        json_body: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(3):
            await self._sleep()
            try:
                response = await client.request(method, url, json=json_body)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise TypeError("Workday returned a non-object JSON response")
                return payload
            except (httpx.HTTPError, TypeError, ValueError) as exc:
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
        site, search_text = self._site_from_shard(shard)
        list_url = f"{site.cxs_base_url}/jobs"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Accept-Language": "de-AT,de;q=0.9,en;q=0.7",
            "Referer": f"{site.public_base_url}/",
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian job search)",
        }

        rows: list[dict[str, Any]] = []
        pages_fetched = 0
        total = 0
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
                    payload = await self._request_json(
                        client,
                        "POST",
                        list_url,
                        json_body={
                            "appliedFacets": {},
                            "limit": _WORKDAY_PAGE_SIZE,
                            "offset": offset,
                            "searchText": search_text,
                        },
                    )
                    page, total = _workday_list(payload)
                    rows.extend(page)
                    pages_fetched += 1
                    offset += len(page)
                    if not page or offset >= total:
                        break
                    if len(page) < _WORKDAY_PAGE_SIZE:
                        break
            except (httpx.HTTPError, TypeError, ValueError) as exc:
                raise SourceFetchError(
                    f"Workday shard {shard.key!r} list fetch failed: {exc}",
                    pages_fetched=pages_fetched,
                    items_seen=0,
                    source_reported_count=total or None,
                    next_cursor={"search_text": search_text, "offset": offset},
                    partial_items=[],
                ) from exc

            items: list[RawJob] = []
            detail_failed: list[str] = []
            seen_ids: set[str] = set()
            for listing in rows:
                external_path = _text(listing.get("externalPath"))
                if external_path is None:
                    continue
                if not external_path.startswith("/"):
                    external_path = f"/{external_path}"
                detail_url = f"{site.cxs_base_url}{external_path}"
                try:
                    detail = await self._request_json(client, "GET", detail_url)
                    job = parse_workday_detail(
                        detail,
                        site=site,
                        listing=listing,
                        austrian_localities=self.austrian_localities,
                    )
                except (httpx.HTTPError, TypeError, ValueError):
                    detail_failed.append(external_path)
                    continue
                if job is None or job.source_listing_id in seen_ids:
                    continue
                seen_ids.add(job.source_listing_id)
                items.append(job)

        next_cursor = {
            "search_text": search_text,
            "source_matches": total,
            "rows_fetched": len(rows),
            "austrian_items": len(items),
            "detail_failed": len(detail_failed),
            "detail_failed_paths": detail_failed[:20],
        }
        if detail_failed:
            raise SourceFetchError(
                f"Workday shard {shard.key!r} had {len(detail_failed)} detail failures",
                pages_fetched=pages_fetched,
                items_seen=len(items),
                source_reported_count=total,
                next_cursor=next_cursor,
                partial_items=items,
            )

        # Search-text shards are deliberately discovery frontiers. Even when every
        # result for a query was traversed, the union is not proof that every Austrian
        # posting on a global Workday board was enumerated, so it has no disappearance
        # authority.
        return SourceBatch(
            items=items,
            next_cursor=next_cursor,
            source_reported_count=total,
            coverage_complete=False,
            result_cap_hit=cap_hit,
            pages_fetched=pages_fetched,
        )
