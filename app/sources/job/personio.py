from __future__ import annotations

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

import httpx

from app.jobs.location_resolution import canonicalize_locality
from app.sources.base import (
    JobSource,
    RawJob,
    RawJobLocation,
    SourceBatch,
    SourceFetchError,
    SourceShardSpec,
)

PERSONIO_BASE_SUFFIX = ".jobs.personio.de"
_SPACE_RE = re.compile(r"\s+")
_POSTAL_CODE_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


@dataclass(frozen=True, slots=True)
class PersonioSite:
    tenant: str
    company: str

    def __post_init__(self) -> None:
        if not self.tenant.strip():
            raise ValueError("Personio tenant must not be empty")
        if not self.company.strip():
            raise ValueError("Personio company must not be empty")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _html_to_text(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    parser = _TextExtractor()
    parser.feed(value)
    normalized = _SPACE_RE.sub(" ", " ".join(parser.parts)).strip()
    return html.unescape(normalized) or None


def _child_text(element: ET.Element, tag: str) -> str | None:
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.casefold().split())


def _contains_austria(value: str) -> bool:
    normalized = _normalize(value)
    return "austria" in normalized or "österreich" in normalized


def _known_localities_in_office(
    office: str,
    austrian_localities: set[str],
) -> list[str]:
    """Return conservative Austrian locality matches from an office label."""
    normalized = _normalize(office)
    if not normalized:
        return []

    # Exact aliases such as Vienna -> Wien should pass before literal matching.
    exact_canonical = canonicalize_locality(office)
    if exact_canonical in austrian_localities:
        return [exact_canonical]

    matches: list[str] = []
    for locality in sorted(austrian_localities, key=len, reverse=True):
        if not locality:
            continue
        pattern = rf"(?<!\w){re.escape(locality)}(?!\w)"
        if re.search(pattern, normalized):
            matches.append(locality)

    # Also resolve aliases in common comma/slash/semicolon-separated multi-office labels.
    for part in re.split(r"[,;/|]", office):
        canonical = canonicalize_locality(part.strip())
        if canonical in austrian_localities and canonical not in matches:
            matches.append(canonical)

    result: list[str] = []
    for match in matches:
        if any(match in existing for existing in result):
            continue
        result.append(match)
    return result


def _fallback_city_from_office(office: str) -> str | None:
    cleaned = _POSTAL_CODE_RE.sub("", office).strip(" ,-–—")
    cleaned = re.sub(
        r"\b(?:austria|österreich)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip(" ,-–—")
    if not cleaned:
        return None
    if "," in cleaned:
        cleaned = cleaned.split(",", 1)[0].strip()
    if " - " in cleaned:
        tail = cleaned.rsplit(" - ", 1)[-1].strip()
        if tail:
            cleaned = tail
    return cleaned or None


def _austrian_locations(
    office: str | None,
    *,
    austrian_localities: set[str],
) -> list[RawJobLocation]:
    if not office or not office.strip():
        return []

    text = _SPACE_RE.sub(" ", office).strip()
    explicit_austria = _contains_austria(text)
    locality_matches = _known_localities_in_office(text, austrian_localities)
    postal_match = _POSTAL_CODE_RE.search(text)
    postal_code = postal_match.group(1) if postal_match else None

    if not explicit_austria and not locality_matches and postal_code is None:
        return []

    cities = locality_matches
    if not cities and explicit_austria:
        fallback = _fallback_city_from_office(text)
        cities = [fallback] if fallback else []

    if not cities:
        return [
            RawJobLocation(
                postal_code=postal_code,
                city=None,
                location_text=text,
                remote=False,
            )
        ]

    return [
        RawJobLocation(
            postal_code=postal_code if len(cities) == 1 else None,
            city=city,
            location_text=text,
            remote=False,
        )
        for city in cities
    ]


def _description(position: ET.Element) -> str | None:
    sections: list[str] = []
    descriptions = position.find("jobDescriptions")
    if descriptions is None:
        return None

    for block in descriptions.findall("jobDescription"):
        heading = _child_text(block, "name")
        body = _html_to_text(_child_text(block, "value"))
        section = "\n".join(part for part in (heading, body) if part)
        if section:
            sections.append(section)
    return "\n\n".join(sections) or None


def parse_personio_position(
    position: ET.Element,
    *,
    site: PersonioSite,
    austrian_localities: set[str],
) -> RawJob | None:
    position_id = _child_text(position, "id")
    title = _child_text(position, "name")
    office = _child_text(position, "office")
    if not position_id:
        raise ValueError(f"Personio tenant {site.tenant!r} returned a position without id")
    if not title:
        raise ValueError(
            f"Personio tenant {site.tenant!r} returned position {position_id!r} without title"
        )

    locations = _austrian_locations(office, austrian_localities=austrian_localities)
    if not locations:
        return None

    metadata: dict[str, Any] = {
        "wohnwerk_personio_tenant": site.tenant,
        "wohnwerk_company": site.company,
        "personio_office": office,
        "personio_subcompany": _child_text(position, "subcompany"),
        "personio_department": _child_text(position, "department"),
        "personio_recruiting_category": _child_text(position, "recruitingCategory"),
        "personio_employment_type": _child_text(position, "employmentType"),
        "personio_seniority": _child_text(position, "seniority"),
        "personio_schedule": _child_text(position, "schedule"),
        "personio_years_of_experience": _child_text(position, "yearsOfExperience"),
    }

    return RawJob(
        source_listing_id=f"{site.tenant}:{position_id}",
        url=f"https://{site.tenant}{PERSONIO_BASE_SUFFIX}/job/{position_id}?language=de",
        title=title,
        company=site.company,
        description=_description(position),
        locations=locations,
        raw_payload=metadata,
    )


def parse_personio_feed(
    payload: bytes,
    *,
    site: PersonioSite,
    austrian_localities: set[str],
) -> tuple[list[RawJob], int]:
    root = ET.fromstring(payload)
    positions = root.findall("position")
    items: list[RawJob] = []
    for position in positions:
        parsed = parse_personio_position(
            position,
            site=site,
            austrian_localities=austrian_localities,
        )
        if parsed is not None:
            items.append(parsed)
    return items, len(positions)


class PersonioJobSource(JobSource):
    """Public Personio career-site XML feeds, one employer tenant per shard."""

    name = "personio-public-xml"

    def __init__(
        self,
        *,
        sites: list[PersonioSite],
        austrian_localities: set[str],
        request_delay_seconds: float = 0.25,
    ) -> None:
        if not sites:
            raise ValueError("At least one Personio tenant is required")
        self.sites = list(sites)
        self.austrian_localities = {
            canonical
            for value in austrian_localities
            if (canonical := canonicalize_locality(value)) is not None
        }
        self.request_delay_seconds = max(0.0, request_delay_seconds)

    def default_shards(self) -> list[SourceShardSpec]:
        return [
            SourceShardSpec(
                key=site.tenant,
                params={"tenant": site.tenant, "company": site.company},
            )
            for site in self.sites
        ]

    @staticmethod
    def _site_from_shard(shard: SourceShardSpec) -> PersonioSite:
        tenant = shard.params.get("tenant")
        company = shard.params.get("company")
        if not isinstance(tenant, str) or not isinstance(company, str):
            raise TypeError(f"Invalid Personio shard parameters for {shard.key!r}")
        return PersonioSite(tenant=tenant, company=company)

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawJob]:
        del cursor, reconciliation
        site = self._site_from_shard(shard)
        if self.request_delay_seconds > 0:
            await asyncio.sleep(self.request_delay_seconds)

        url = f"https://{site.tenant}{PERSONIO_BASE_SUFFIX}/xml"
        headers = {
            "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.1",
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian job search)",
        }

        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=30.0,
                follow_redirects=True,
            ) as client:
                response = await client.get(url, params={"language": "de"})
                response.raise_for_status()
                items, total_positions = parse_personio_feed(
                    response.content,
                    site=site,
                    austrian_localities=self.austrian_localities,
                )
        except Exception as exc:
            raise SourceFetchError(
                f"Personio shard {shard.key!r} failed: {exc}",
                pages_fetched=0,
                items_seen=0,
                source_reported_count=None,
                next_cursor={},
                partial_items=[],
            ) from exc

        return SourceBatch(
            items=items,
            next_cursor={"source_positions": total_positions},
            source_reported_count=total_positions,
            coverage_complete=True,
            result_cap_hit=False,
            pages_fetched=1,
        )
