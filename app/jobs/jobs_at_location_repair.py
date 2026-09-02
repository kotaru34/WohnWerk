from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.location_resolution import canonicalize_locality
from app.models import JobListing, JobLocation, ListingStatus, Source
from app.sources.job.jobs_at import _DetailPageParser, _visible_header_location


@dataclass(frozen=True, slots=True)
class JobsAtLocationRepairSummary:
    considered: int = 0
    repaired: int = 0
    unresolved: int = 0
    failed: int = 0


def parse_jobs_at_visible_location(content: str):
    """Extract the concrete visible jobs.at header location, if one is present."""
    parser = _DetailPageParser()
    parser.feed(content)
    return _visible_header_location(parser.text_parts, remote=False)


def _needs_source_repair(location: JobLocation) -> bool:
    if location.location is not None:
        return False
    # A concrete city that merely failed normal geocoding belongs to the local
    # punctuation-safe fallback, not another external request.
    return not bool(location.city and canonicalize_locality(location.city) is not None)


def repair_unresolved_jobs_at_locations(
    session: Session,
    *,
    limit: int = 20,
    timeout_seconds: float = 20.0,
    request_delay_seconds: float = 0.35,
) -> JobsAtLocationRepairSummary:
    """Prefer jobs.at's concrete visible locality over region-only structured metadata.

    Some jobs.at pages expose a broad Schema.org region (for example `Kärnten`) while the
    visible job header says `Klagenfurt`. The source page is authoritative for this repair.
    We only replace missing/non-point city data and never overwrite an existing concrete
    locality.
    """
    rows = list(
        session.execute(
            select(JobLocation, JobListing)
            .join(JobListing, JobListing.job_id == JobLocation.job_id)
            .join(Source, Source.id == JobListing.source_id)
            .where(
                JobLocation.location.is_(None),
                JobListing.status == ListingStatus.ACTIVE,
                Source.name == "jobs.at",
            )
            .order_by(JobLocation.id, JobListing.id)
        )
    )

    considered = 0
    repaired = 0
    unresolved = 0
    failed = 0
    seen_location_ids: set[int] = set()

    headers = {
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
        "User-Agent": (
            "WohnWerk/0.1 (+private self-hosted Austrian job search; "
            "location repair)"
        ),
    }

    with httpx.Client(headers=headers, timeout=timeout_seconds, follow_redirects=True) as client:
        for location, listing in rows:
            if location.id in seen_location_ids or not _needs_source_repair(location):
                continue
            if considered >= max(1, limit):
                break
            seen_location_ids.add(location.id)
            considered += 1

            try:
                response = client.get(listing.url)
                response.raise_for_status()
            except httpx.HTTPError:
                failed += 1
                continue

            visible = parse_jobs_at_visible_location(response.text)
            if (
                visible is None
                or not visible.city
                or canonicalize_locality(visible.city) is None
            ):
                unresolved += 1
                continue

            location.city = visible.city
            location.postal_code = visible.postal_code or location.postal_code
            location.location_text = visible.location_text or visible.city
            repaired += 1

            if request_delay_seconds > 0:
                time.sleep(request_delay_seconds)

    return JobsAtLocationRepairSummary(
        considered=considered,
        repaired=repaired,
        unresolved=unresolved,
        failed=failed,
    )
