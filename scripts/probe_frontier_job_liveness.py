from __future__ import annotations

import argparse
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import exists, select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.jobs.liveness import assess_http_page
from app.models import Job, JobListing, ListingStatus, Source

FRONTIER_SOURCE_NAMES = (
    "karriere.at",
    "jobs.at",
    "stepstone.at",
    "willhaben-jobs",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Conservatively probe stale active frontier job URLs. Only explicit closure "
            "evidence (404/410 or known closed-page text) deactivates a listing."
        )
    )
    parser.add_argument(
        "--stale-hours",
        type=float,
        default=24.0,
        help="Only probe listings not rediscovered for at least this many hours (default: 24).",
    )
    parser.add_argument(
        "--max-listings",
        type=int,
        default=200,
        help="Maximum listings probed in one sweep (default: 200).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.4,
        help="Delay between public-page probes in seconds (default: 0.4).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Per-request timeout in seconds (default: 15).",
    )
    return parser.parse_args()


def _gate_accepted(listing: JobListing) -> bool:
    payload = listing.raw_payload or {}
    gate = payload.get("wohnwerk_discovery_gate")
    return isinstance(gate, dict) and gate.get("accepted") is True


def _record_probe(
    listing: JobListing,
    *,
    checked_at: datetime,
    state: str,
    status_code: int | None,
    final_url: str | None,
    reasons: tuple[str, ...],
    error: str | None = None,
) -> None:
    payload = dict(listing.raw_payload or {})
    payload["wohnwerk_liveness"] = {
        "checked_at": checked_at.isoformat(),
        "state": state,
        "status_code": status_code,
        "final_url": final_url,
        "reasons": list(reasons),
        "error": error,
    }
    listing.raw_payload = payload


def _sync_jobs(session, job_ids: set[int], *, now: datetime) -> int:
    retired = 0
    for job_id in job_ids:
        job = session.get(Job, job_id)
        if job is None:
            continue
        has_active_listing = session.scalar(
            select(
                exists().where(
                    JobListing.job_id == job_id,
                    JobListing.status == ListingStatus.ACTIVE,
                )
            )
        )
        if has_active_listing:
            continue
        if job.status != ListingStatus.INACTIVE:
            retired += 1
        job.status = ListingStatus.INACTIVE
        job.inactive_at = now
    return retired


def main() -> None:
    args = parse_args()
    if args.stale_hours <= 0:
        raise SystemExit("--stale-hours must be positive")
    if args.max_listings <= 0:
        raise SystemExit("--max-listings must be positive")

    now = datetime.now(UTC)
    stale_before = now - timedelta(hours=args.stale_hours)
    headers = {
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.7",
        "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian job search; liveness check)",
    }

    with SessionLocal() as session:
        sources = list(
            session.scalars(
                select(Source).where(
                    Source.enabled.is_(True),
                    Source.name.in_(FRONTIER_SOURCE_NAMES),
                )
            )
        )
        source_ids = {source.id for source in sources}
        if not source_ids:
            print("liveness_status=ok candidates=0 reason=no_enabled_frontier_sources")
            return

        listings = list(
            session.scalars(
                select(JobListing)
                .where(
                    JobListing.source_id.in_(source_ids),
                    JobListing.status == ListingStatus.ACTIVE,
                    JobListing.last_seen_at <= stale_before,
                )
                .options(selectinload(JobListing.job))
                .order_by(JobListing.last_seen_at, JobListing.id)
                .limit(args.max_listings)
            )
        )
        listings = [listing for listing in listings if _gate_accepted(listing)]

        counts: Counter[str] = Counter()
        touched_jobs: set[int] = set()
        with httpx.Client(headers=headers, timeout=args.timeout, follow_redirects=True) as client:
            for listing in listings:
                if args.delay > 0:
                    time.sleep(args.delay)
                checked_at = datetime.now(UTC)
                try:
                    response = client.get(listing.url)
                except httpx.HTTPError as exc:
                    counts["unknown"] += 1
                    _record_probe(
                        listing,
                        checked_at=checked_at,
                        state="unknown",
                        status_code=None,
                        final_url=None,
                        reasons=("request_failed",),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    session.commit()
                    continue

                assessment = assess_http_page(response.status_code, response.text)
                counts[assessment.state] += 1
                _record_probe(
                    listing,
                    checked_at=checked_at,
                    state=assessment.state,
                    status_code=response.status_code,
                    final_url=str(response.url),
                    reasons=assessment.reasons,
                )
                if assessment.state == "dead":
                    listing.status = ListingStatus.INACTIVE
                    listing.inactive_at = checked_at
                    touched_jobs.add(listing.job_id)
                    print(
                        f"retired listing={listing.id} job={listing.job_id} "
                        f"source={listing.source_id} reasons={','.join(assessment.reasons)}"
                    )
                session.commit()

        retired_jobs = _sync_jobs(session, touched_jobs, now=datetime.now(UTC))
        session.commit()

        print("liveness_status=ok")
        print(f"stale_candidates={len(listings)}")
        print(f"live={counts['live']}")
        print(f"unknown={counts['unknown']}")
        print(f"dead={counts['dead']}")
        print(f"canonical_jobs_retired={retired_jobs}")
        print("policy=fail-closed only explicit dead evidence deactivates")


if __name__ == "__main__":
    main()
