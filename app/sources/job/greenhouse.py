from __future__ import annotations

import html
import re
from dataclasses import dataclass
from decimal import Decimal
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
from app.sources.job.salary_detail_selection import salary_detail_candidates

# Greenhouse documents one public Job Board API host for published boards. The
# browser-facing career UI may live on job-boards.eu.greenhouse.io, but that does
# not imply a boards-api.eu.greenhouse.io API endpoint.
GLOBAL_API_BASE = "https://boards-api.greenhouse.io/v1/boards"
EU_API_BASE = GLOBAL_API_BASE

_POSTAL_CODE_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_SPACE_RE = re.compile(r"\s+")
_COUNTRY_RE = re.compile(r"\b(?:austria|österreich)\b", flags=re.IGNORECASE)
_REMOTE_RE = re.compile(r"\b(?:remote|home\s*office|homeoffice)\b", flags=re.IGNORECASE)
_LOCATION_SPLIT_RE = re.compile(r"\s*;\s*|\s*\n+\s*")
_PAY_ANNUAL_RE = re.compile(
    r"(?:\bannual(?:ly)?\b|\bper\s+year\b|\byearly\b|\bjahr(?:es|lich)?\w*\b|"
    r"\bbased\s+on\s+14\s+months\b|\b14\s+months\b|\b14\s+monatsgehälter\b)",
    flags=re.IGNORECASE,
)
_PAY_MONTHLY_RE = re.compile(
    r"(?:\bmonthly\b|\bper\s+month\b|\bmonat(?:lich)?\w*\b)",
    flags=re.IGNORECASE,
)
_PAY_HOURLY_RE = re.compile(
    r"(?:\bhourly\b|\bper\s+hour\b|\bstündlich\b|\bstuendlich\b)",
    flags=re.IGNORECASE,
)
_PAY_AUSTRIA_RE = re.compile(r"\b(?:austria(?:n)?|österreich(?:isch\w*)?)\b", re.IGNORECASE)
_NON_CITY_TOKENS = {
    "austria",
    "österreich",
    "remote",
    "home office",
    "homeoffice",
}
_OTHER_COUNTRY_TOKENS = {
    "germany",
    "deutschland",
    "spain",
    "spanien",
    "france",
    "frankreich",
    "italy",
    "italien",
    "switzerland",
    "schweiz",
    "netherlands",
    "niederlande",
    "slovenia",
    "slowenien",
    "croatia",
    "kroatien",
    "hungary",
    "ungarn",
    "poland",
    "polen",
    "portugal",
    "united kingdom",
    "uk",
    "romania",
    "rumänien",
    "rumaenien",
}


@dataclass(frozen=True, slots=True)
class GreenhouseBoard:
    token: str
    company: str
    region: str = "global"

    def __post_init__(self) -> None:
        if self.region not in {"global", "eu"}:
            raise ValueError(f"Unsupported Greenhouse region: {self.region!r}")
        if not self.token.strip():
            raise ValueError("Greenhouse board token must not be empty")
        if not self.company.strip():
            raise ValueError("Greenhouse company must not be empty")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        cleaned = _SPACE_RE.sub(" ", data).strip()
        if cleaned:
            self.parts.append(cleaned)


def _html_to_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None

    decoded = value
    for _ in range(2):
        updated = html.unescape(decoded)
        if updated == decoded:
            break
        decoded = updated

    parser = _TextExtractor()
    parser.feed(decoded)
    normalized = "\n".join(parser.parts).strip()
    return normalized or None


def _looks_austrian(text: str) -> bool:
    return _COUNTRY_RE.search(text) is not None


def _location_texts(payload: dict[str, Any]) -> list[str]:
    location = payload.get("location")
    if not isinstance(location, dict):
        return []
    name = location.get("name")
    if not isinstance(name, str) or not name.strip():
        return []

    result: list[str] = []
    seen: set[str] = set()
    for part in _LOCATION_SPLIT_RE.split(name):
        cleaned = _SPACE_RE.sub(" ", part).strip(" ,-–—")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _extract_city(text: str) -> str | None:
    cleaned = _POSTAL_CODE_RE.sub("", text)
    parts = [part.strip(" ,-–—") for part in cleaned.split(",") if part.strip(" ,-–—")]
    if not parts:
        return None

    austria_index: int | None = None
    for index, part in enumerate(parts):
        if _COUNTRY_RE.search(part):
            austria_index = index
            break
    if austria_index is None or austria_index == 0:
        return None

    candidate = parts[0]
    normalized = candidate.casefold()
    if normalized in _NON_CITY_TOKENS or normalized in _OTHER_COUNTRY_TOKENS:
        return None
    if _REMOTE_RE.search(candidate):
        return None
    return candidate or None


def _austrian_locations(payload: dict[str, Any]) -> list[RawJobLocation]:
    locations: list[RawJobLocation] = []
    seen: set[tuple[str | None, str | None, str, bool]] = set()

    for text in _location_texts(payload):
        if not _looks_austrian(text):
            continue

        remote = _REMOTE_RE.search(text) is not None
        postal_match = _POSTAL_CODE_RE.search(text)
        postal_code = postal_match.group(1) if postal_match else None
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


def _pay_period(title: str) -> str | None:
    if _PAY_ANNUAL_RE.search(title):
        return "year"
    if _PAY_MONTHLY_RE.search(title):
        return "month"
    if _PAY_HOURLY_RE.search(title):
        return "hour"
    return None


def _pay_amount_from_cents(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return Decimal(value) / Decimal(100)


def _plausible_structured_pay(value: Decimal, period: str) -> bool:
    if period == "year":
        return Decimal(10000) <= value <= Decimal(500000)
    if period == "month":
        return Decimal(800) <= value <= Decimal(30000)
    if period == "hour":
        return Decimal(5) <= value <= Decimal(500)
    return False


def apply_greenhouse_pay_input_ranges(item: RawJob, payload: dict[str, Any]) -> bool:
    """Apply one unambiguous EUR pay-transparency range with explicit period semantics."""
    ranges = payload.get("pay_input_ranges")
    if not isinstance(ranges, list):
        return False

    candidates: list[tuple[dict[str, Any], Decimal, Decimal | None, str, str]] = []
    for row in ranges:
        if not isinstance(row, dict):
            continue
        currency = row.get("currency_type")
        title = row.get("title")
        if not isinstance(currency, str) or currency.upper() != "EUR":
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        period = _pay_period(title)
        if period is None:
            continue

        minimum = _pay_amount_from_cents(row.get("min_cents"))
        maximum = _pay_amount_from_cents(row.get("max_cents"))
        if minimum is None and maximum is None:
            continue
        if minimum is None:
            minimum = maximum
            maximum = None
        assert minimum is not None
        if not _plausible_structured_pay(minimum, period):
            continue
        if maximum is not None:
            if not _plausible_structured_pay(maximum, period):
                continue
            if maximum < minimum:
                minimum, maximum = maximum, minimum
        candidates.append((row, minimum, maximum, period, title.strip()))

    if not candidates:
        return False

    austrian = [candidate for candidate in candidates if _PAY_AUSTRIA_RE.search(candidate[4])]
    if len(austrian) == 1:
        selected = austrian[0]
    elif len(candidates) == 1:
        selected = candidates[0]
    else:
        numeric = {(minimum, maximum, period) for _row, minimum, maximum, period, _title in candidates}
        if len(numeric) != 1:
            return False
        selected = candidates[0]

    row, minimum, maximum, period, title = selected
    item.salary_min = minimum
    item.salary_max = maximum
    item.salary_currency = "EUR"
    item.salary_period = period
    item.salary_provenance = "STRUCTURED"
    item.salary_confidence = Decimal("1.000")
    item.salary_is_minimum_only = maximum is None
    amount_text = f"EUR {minimum}"
    if maximum is not None:
        amount_text += f"–{maximum}"
    item.salary_text = f"{title}: {amount_text}"

    raw_payload = dict(item.raw_payload)
    raw_payload["wohnwerk_greenhouse_pay_input_range"] = dict(row)
    raw_payload["wohnwerk_greenhouse_pay_period"] = period
    item.raw_payload = raw_payload
    return True


def parse_greenhouse_posting(
    payload: dict[str, Any],
    *,
    board: GreenhouseBoard,
) -> RawJob | None:
    posting_id = payload.get("id")
    title = payload.get("title")
    absolute_url = payload.get("absolute_url")

    if isinstance(posting_id, bool) or not isinstance(posting_id, (int, str)):
        raise TypeError("Greenhouse posting is missing a stable id")
    posting_id_text = str(posting_id).strip()
    if not posting_id_text:
        raise ValueError("Greenhouse posting is missing a stable id")
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"Greenhouse posting {posting_id_text!r} is missing a title")
    if not isinstance(absolute_url, str) or not absolute_url.startswith("https://"):
        raise ValueError(f"Greenhouse posting {posting_id_text!r} is missing an absolute URL")

    locations = _austrian_locations(payload)
    if not locations:
        return None

    raw_payload = dict(payload)
    raw_payload["wohnwerk_greenhouse_board"] = board.token
    raw_payload["wohnwerk_greenhouse_region"] = board.region
    raw_payload["wohnwerk_company"] = board.company

    item = RawJob(
        source_listing_id=f"{board.region}:{board.token}:{posting_id_text}",
        url=absolute_url,
        title=title.strip(),
        company=board.company,
        description=_html_to_text(payload.get("content")),
        locations=locations,
        raw_payload=raw_payload,
    )
    apply_greenhouse_pay_input_ranges(item, payload)
    return item


class GreenhouseJobSource(JobSource):
    """Complete published-job feeds for explicitly configured Greenhouse boards.

    Greenhouse's public Job Board API returns the full published board in one request.
    Each employer board is a separate WohnWerk shard so a failed tenant cannot affect
    lifecycle authority for another employer. Public per-post pay-transparency details
    are optional enrichment and never determine coverage completeness.
    """

    name = "greenhouse-public-job-board"

    def __init__(
        self,
        *,
        boards: list[GreenhouseBoard],
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not boards:
            raise ValueError("At least one Greenhouse board is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.boards = list(boards)
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=board.token,
                params={
                    "token": board.token,
                    "company": board.company,
                    "region": board.region,
                },
            )
            for board in self.boards
        ]

    @staticmethod
    def _board_from_shard(shard: SourceShardSpec) -> GreenhouseBoard:
        token = shard.params.get("token")
        company = shard.params.get("company")
        region = shard.params.get("region", "global")
        if not isinstance(token, str) or not isinstance(company, str) or not isinstance(region, str):
            raise TypeError(f"Invalid Greenhouse shard parameters for {shard.key!r}")
        return GreenhouseBoard(token=token, company=company, region=region)

    @staticmethod
    def _api_base(board: GreenhouseBoard) -> str:
        del board
        return GLOBAL_API_BASE

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawJob]:
        del cursor, reconciliation
        board = self._board_from_shard(shard)
        url = f"{self._api_base(board)}/{board.token}/jobs"
        headers = {
            "Accept": "application/json",
            "User-Agent": "WohnWerk/0.3 (+private self-hosted Austrian job search)",
        }

        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = await client.get(url, params={"content": "true"})
                response.raise_for_status()
                payload = response.json()

                if not isinstance(payload, dict):
                    raise TypeError(
                        f"Greenhouse board {board.token!r} returned "
                        f"{type(payload).__name__}, expected object"
                    )
                jobs = payload.get("jobs")
                if not isinstance(jobs, list) or not all(isinstance(item, dict) for item in jobs):
                    raise TypeError(
                        f"Greenhouse board {board.token!r} returned a malformed jobs list"
                    )

                items: list[RawJob] = []
                for posting in jobs:
                    parsed = parse_greenhouse_posting(posting, board=board)
                    if parsed is not None:
                        items.append(parsed)

                detail_candidates = salary_detail_candidates(items)
                detail_fetched = 0
                detail_failed = 0
                pay_ranges_found = sum(item.salary_min is not None for item in items)

                for item in detail_candidates:
                    posting_id = item.raw_payload.get("id")
                    if isinstance(posting_id, bool) or not isinstance(posting_id, (int, str)):
                        continue
                    detail_url = f"{url}/{posting_id}"
                    try:
                        detail_response = await client.get(
                            detail_url,
                            params={
                                "content": "true",
                                "pay_transparency": "true",
                                "pay_input_ranges": "true",
                            },
                        )
                        detail_response.raise_for_status()
                        detail_payload = detail_response.json()
                        if not isinstance(detail_payload, dict):
                            raise TypeError("Greenhouse detail response is not an object")
                    except (httpx.HTTPError, TypeError, ValueError) as exc:
                        raw_payload = dict(item.raw_payload)
                        raw_payload["greenhouse_pay_detail_error"] = (
                            f"{type(exc).__name__}: {exc}"
                        )
                        item.raw_payload = raw_payload
                        detail_failed += 1
                        continue

                    detail_fetched += 1
                    raw_payload = dict(item.raw_payload)
                    raw_payload["greenhouse_pay_detail_fetched"] = True
                    if "pay_input_ranges" in detail_payload:
                        raw_payload["greenhouse_pay_input_ranges"] = detail_payload[
                            "pay_input_ranges"
                        ]
                    item.raw_payload = raw_payload
                    if apply_greenhouse_pay_input_ranges(item, detail_payload):
                        pay_ranges_found += 1

            meta = payload.get("meta")
            total = meta.get("total") if isinstance(meta, dict) else None
            source_reported_count = (
                total if isinstance(total, int) and not isinstance(total, bool) else len(jobs)
            )

            return SourceBatch(
                items=items,
                next_cursor={
                    "pay_detail_candidates": len(detail_candidates),
                    "pay_details_fetched": detail_fetched,
                    "pay_details_failed": detail_failed,
                    "pay_ranges_found": pay_ranges_found,
                },
                source_reported_count=source_reported_count,
                coverage_complete=True,
                result_cap_hit=False,
                pages_fetched=1 + detail_fetched + detail_failed,
            )
        except Exception as exc:
            raise SourceFetchError(
                f"Greenhouse shard {shard.key!r} failed: {exc}",
                pages_fetched=0,
                items_seen=0,
                source_reported_count=None,
                next_cursor={},
            ) from exc
