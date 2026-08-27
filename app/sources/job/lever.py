from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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

GLOBAL_API_BASE = "https://api.lever.co/v0/postings"
EU_API_BASE = "https://api.eu.lever.co/v0/postings"

_POSTAL_CODE_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_SPACE_RE = re.compile(r"\s+")

_INTERVAL_MAP = {
    "per-year-salary": "year",
    "per-month-salary": "month",
    "semi-month-salary": "semi_month",
    "bi-month-salary": "bi_month",
    "bi-week-salary": "bi_week",
    "per-week-salary": "week",
    "per-day-wage": "day",
    "per-hour-wage": "hour",
    "one-time": "one_time",
}


@dataclass(frozen=True, slots=True)
class LeverSite:
    site: str
    company: str
    region: str = "eu"

    def __post_init__(self) -> None:
        if self.region not in {"eu", "global"}:
            raise ValueError(f"Unsupported Lever region: {self.region!r}")
        if not self.site.strip():
            raise ValueError("Lever site must not be empty")
        if not self.company.strip():
            raise ValueError("Lever company must not be empty")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _html_to_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parser = _TextExtractor()
    parser.feed(value)
    normalized = _SPACE_RE.sub(" ", " ".join(parser.parts)).strip()
    return html.unescape(normalized) or None


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _salary_period(interval: Any) -> str | None:
    if not isinstance(interval, str) or not interval.strip():
        return None
    normalized = interval.strip().lower()
    return _INTERVAL_MAP.get(normalized, normalized[:20])


def _extract_postal_code(text: str) -> str | None:
    match = _POSTAL_CODE_RE.search(text)
    return match.group(1) if match else None


def _looks_austrian(text: str) -> bool:
    normalized = text.casefold()
    return "austria" in normalized or "österreich" in normalized


def _extract_city(text: str) -> str | None:
    candidate = text.strip()
    if not candidate:
        return None

    candidate = _POSTAL_CODE_RE.sub("", candidate).strip(" ,-–—")
    candidate = re.sub(r"\([^)]*(?:austria|österreich|remote|home office)[^)]*\)", "", candidate, flags=re.I)
    candidate = candidate.split("/")[0].strip()
    candidate = candidate.split(",")[0].strip()
    if candidate.casefold() in {"austria", "österreich", "remote", "home office"}:
        return None
    return candidate or None


def _location_texts(payload: dict[str, Any]) -> list[str]:
    categories = payload.get("categories")
    if not isinstance(categories, dict):
        categories = {}

    values = categories.get("allLocations")
    raw_locations: list[Any]
    if isinstance(values, list):
        raw_locations = values
    else:
        raw_locations = []

    primary = categories.get("location")
    if not raw_locations and isinstance(primary, str):
        raw_locations = [primary]

    result: list[str] = []
    seen: set[str] = set()
    for value in raw_locations:
        if not isinstance(value, str):
            continue
        cleaned = _SPACE_RE.sub(" ", value).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _austrian_locations(payload: dict[str, Any]) -> list[RawJobLocation]:
    country = payload.get("country")
    country_code = country.upper() if isinstance(country, str) else None
    texts = _location_texts(payload)
    workplace_type = str(payload.get("workplaceType") or "").casefold()

    if country_code != "AT":
        texts = [text for text in texts if _looks_austrian(text)]
        if not texts:
            return []

    if not texts and country_code == "AT":
        texts = ["Austria"]

    locations: list[RawJobLocation] = []
    seen: set[tuple[str | None, str | None, str, bool]] = set()
    for text in texts:
        remote = workplace_type == "remote" or any(
            marker in text.casefold() for marker in ("remote", "home office")
        )
        postal_code = _extract_postal_code(text)
        city = _extract_city(text)
        key = (postal_code, city.casefold() if city else None, text.casefold(), remote)
        if key in seen:
            continue
        seen.add(key)
        locations.append(
            RawJobLocation(
                postal_code=postal_code,
                city=city,
                location_text=text,
                remote=remote,
            )
        )
    return locations


def _description(payload: dict[str, Any]) -> str | None:
    parts: list[str] = []

    description = payload.get("descriptionPlain")
    if isinstance(description, str) and description.strip():
        parts.append(description.strip())

    lists = payload.get("lists")
    if isinstance(lists, list):
        for block in lists:
            if not isinstance(block, dict):
                continue
            heading = block.get("text")
            body = _html_to_text(block.get("content"))
            section = "\n".join(
                value
                for value in (
                    heading.strip() if isinstance(heading, str) and heading.strip() else None,
                    body,
                )
                if value
            )
            if section:
                parts.append(section)

    additional = payload.get("additionalPlain")
    if isinstance(additional, str) and additional.strip():
        parts.append(additional.strip())

    return "\n\n".join(parts) or None


def parse_lever_posting(
    payload: dict[str, Any],
    *,
    site: LeverSite,
) -> RawJob | None:
    posting_id = payload.get("id")
    title = payload.get("text")
    hosted_url = payload.get("hostedUrl")
    if not isinstance(posting_id, str) or not posting_id.strip():
        raise ValueError("Lever posting is missing a stable id")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"Lever posting {posting_id!r} is missing a title")
    if not isinstance(hosted_url, str) or not hosted_url.startswith("https://"):
        raise ValueError(f"Lever posting {posting_id!r} is missing a hosted URL")

    locations = _austrian_locations(payload)
    if not locations:
        return None

    salary = payload.get("salaryRange")
    if not isinstance(salary, dict):
        salary = {}

    salary_min = _as_decimal(salary.get("min"))
    salary_max = _as_decimal(salary.get("max"))
    salary_currency = salary.get("currency")
    if not isinstance(salary_currency, str) or not salary_currency.strip():
        salary_currency = None

    salary_text = payload.get("salaryDescriptionPlain")
    if not isinstance(salary_text, str) or not salary_text.strip():
        salary_text = None

    has_structured_salary = any(
        value is not None for value in (salary_min, salary_max, salary_currency)
    )

    raw_payload = dict(payload)
    raw_payload["wohnwerk_lever_site"] = site.site
    raw_payload["wohnwerk_lever_region"] = site.region
    raw_payload["wohnwerk_company"] = site.company

    return RawJob(
        source_listing_id=f"{site.region}:{site.site}:{posting_id}",
        url=hosted_url,
        title=title.strip(),
        company=site.company,
        description=_description(payload),
        salary_text=salary_text.strip() if salary_text else None,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency.upper() if salary_currency else None,
        salary_period=_salary_period(salary.get("interval")),
        salary_payment_count=None,
        salary_provenance="EXPLICIT" if has_structured_salary else None,
        salary_confidence=Decimal(1) if has_structured_salary else None,
        salary_is_minimum_only=None,
        locations=locations,
        raw_payload=raw_payload,
    )


class LeverJobSource(JobSource):
    """Complete published-job feeds for explicitly configured Lever tenants.

    Lever's public Postings API exposes only published postings. Each tenant is a
    separate WohnWerk shard, so a failing employer feed cannot make another
    employer authoritative or cause unrelated jobs to disappear.
    """

    name = "lever-public-postings"

    def __init__(
        self,
        *,
        sites: list[LeverSite],
        request_delay_seconds: float = 0.25,
        incremental_pages: int = 1,
        page_size: int = 100,
        hard_max_pages: int = 100,
    ) -> None:
        if not sites:
            raise ValueError("At least one Lever site is required")
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        if incremental_pages <= 0:
            raise ValueError("incremental_pages must be positive")
        if hard_max_pages <= 0:
            raise ValueError("hard_max_pages must be positive")

        self.sites = list(sites)
        self.request_delay_seconds = max(0.0, request_delay_seconds)
        self.incremental_pages = incremental_pages
        self.page_size = page_size
        self.hard_max_pages = hard_max_pages

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=f"{site.region}:{site.site}",
                params={
                    "site": site.site,
                    "company": site.company,
                    "region": site.region,
                },
            )
            for site in self.sites
        ]

    @staticmethod
    def _site_from_shard(shard: SourceShardSpec) -> LeverSite:
        site = shard.params.get("site")
        company = shard.params.get("company")
        region = shard.params.get("region", "eu")
        if not isinstance(site, str) or not isinstance(company, str) or not isinstance(region, str):
            raise ValueError(f"Invalid Lever shard parameters for {shard.key!r}")
        return LeverSite(site=site, company=company, region=region)

    @staticmethod
    def _api_base(site: LeverSite) -> str:
        return EU_API_BASE if site.region == "eu" else GLOBAL_API_BASE

    async def _request_page(
        self,
        client: httpx.AsyncClient,
        *,
        site: LeverSite,
        skip: int,
    ) -> list[dict[str, Any]]:
        url = f"{self._api_base(site)}/{site.site}"
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await client.get(
                    url,
                    params={
                        "mode": "json",
                        "skip": skip,
                        "limit": self.page_size,
                    },
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    response.raise_for_status()
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError(
                        f"Lever {site.site!r} returned {type(payload).__name__}, expected list"
                    )
                if not all(isinstance(item, dict) for item in payload):
                    raise ValueError(f"Lever {site.site!r} returned a malformed postings list")
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt == 2:
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
        del cursor  # Published feeds are rescanned from the newest/current frontier each run.
        site = self._site_from_shard(shard)
        max_pages = self.hard_max_pages if reconciliation else min(
            self.incremental_pages, self.hard_max_pages
        )
        items: list[RawJob] = []
        seen_ids: set[str] = set()
        pages_fetched = 0
        raw_postings_seen = 0

        headers = {
            "Accept": "application/json",
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian job search)",
        }

        async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True) as client:
            try:
                for page_index in range(max_pages):
                    if page_index and self.request_delay_seconds > 0:
                        await asyncio.sleep(self.request_delay_seconds)
                    page = await self._request_page(
                        client,
                        site=site,
                        skip=page_index * self.page_size,
                    )
                    pages_fetched += 1
                    raw_postings_seen += len(page)

                    for payload in page:
                        posting_id = payload.get("id")
                        if isinstance(posting_id, str) and posting_id in seen_ids:
                            continue
                        parsed = parse_lever_posting(payload, site=site)
                        if isinstance(posting_id, str):
                            seen_ids.add(posting_id)
                        if parsed is not None:
                            items.append(parsed)

                    if len(page) < self.page_size:
                        return SourceBatch(
                            items=items,
                            next_cursor={},
                            source_reported_count=None,
                            coverage_complete=True,
                            result_cap_hit=False,
                            pages_fetched=pages_fetched,
                        )

                if reconciliation:
                    return SourceBatch(
                        items=items,
                        next_cursor={"skip": max_pages * self.page_size},
                        source_reported_count=None,
                        coverage_complete=False,
                        result_cap_hit=True,
                        pages_fetched=pages_fetched,
                    )

                return SourceBatch(
                    items=items,
                    next_cursor={"skip": max_pages * self.page_size},
                    source_reported_count=None,
                    coverage_complete=False,
                    result_cap_hit=False,
                    pages_fetched=pages_fetched,
                )
            except Exception as exc:
                raise SourceFetchError(
                    f"Lever shard {shard.key!r} failed after {pages_fetched} pages: {exc}",
                    pages_fetched=pages_fetched,
                    items_seen=len(items),
                    source_reported_count=None,
                    next_cursor={"skip": pages_fetched * self.page_size},
                    partial_items=items,
                ) from exc
