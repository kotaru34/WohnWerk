from __future__ import annotations

import argparse
import time
from collections import Counter
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.jobs.liveness import assess_http_page, released_age_days
from app.models import JobListing, ListingStatus, Source

_SOURCE_NAME = "smartrecruiters-public-postings"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    state: str
    status_code: int | None
    final_url: str | None
    reasons: tuple[str, ...]
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only liveness/freshness audit for current relevant SmartRecruiters listings."
        )
    )
    parser.add_argument("--tenant", help="Only inspect one SmartRecruiters tenant.")
    parser.add_argument("--contains", help="Only inspect titles containing this text.")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.2,
        help="Delay between HTTP probes in seconds (default: 0.2).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Per-request timeout in seconds (default: 20).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print every checked listing, not only suspicious/unknown rows.",
    )
    return parser.parse_args()


def _gate_accepted(listing: JobListing) -> bool:
    payload = listing.raw_payload or {}
    gate = payload.get("wohnwerk_discovery_gate")
    return isinstance(gate, dict) and gate.get("accepted") is True


def _tenant(payload: dict) -> str:
    value = payload.get("wohnwerk_smartrecruiters_tenant")
    return str(value) if value else "unknown"


def _probe(client: httpx.Client, url: str | None, *, delay: float) -> ProbeResult:
    if not url:
        return ProbeResult("unknown", None, None, ("missing_url",))
    if delay > 0:
        time.sleep(delay)
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        return ProbeResult("unknown", None, None, ("request_failed",), str(exc))

    assessment = assess_http_page(response.status_code, response.text)
    return ProbeResult(
        assessment.state,
        response.status_code,
        str(response.url),
        assessment.reasons,
    )


def _overall_state(public: ProbeResult, apply: ProbeResult) -> str:
    if public.state == "dead" or apply.state == "dead":
        return "dead"
    if public.state == "live" and apply.state == "live":
        return "live_confirmed"
    if public.state == "live" or apply.state == "live":
        return "live_partial"
    return "unknown"


def _format_probe(label: str, probe: ProbeResult) -> str:
    status = str(probe.status_code) if probe.status_code is not None else "-"
    reasons = ",".join(probe.reasons) if probe.reasons else "-"
    return f"{label}={probe.state}/{status}/{reasons}"


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == _SOURCE_NAME))
        if source is None:
            print(f"source_not_found={_SOURCE_NAME}")
            return

        listings = list(
            session.scalars(
                select(JobListing)
                .where(
                    JobListing.source_id == source.id,
                    JobListing.status == ListingStatus.ACTIVE,
                )
                .options(selectinload(JobListing.job))
                .order_by(JobListing.id)
            )
        )
        listings = [listing for listing in listings if _gate_accepted(listing)]
        if args.tenant:
            listings = [
                listing
                for listing in listings
                if _tenant(listing.raw_payload or {}) == args.tenant
            ]
        if args.contains:
            needle = args.contains.casefold()
            listings = [
                listing
                for listing in listings
                if needle in (listing.job.title or "").casefold()
            ]

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-AT,de;q=0.9,en;q=0.7",
            "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian job search; liveness audit)",
        }
        state_counts: Counter[str] = Counter()
        age_counts: Counter[str] = Counter()
        missing_apply = 0
        checked = 0

        with httpx.Client(
            headers=headers,
            timeout=args.timeout,
            follow_redirects=True,
        ) as client:
            for listing in listings:
                payload = listing.raw_payload or {}
                released = payload.get("smartrecruiters_released_date")
                apply_url = payload.get("smartrecruiters_apply_url")
                age = released_age_days(released)
                if age is None:
                    age_bucket = "unknown"
                elif age <= 30:
                    age_bucket = "0-30d"
                elif age <= 90:
                    age_bucket = "31-90d"
                elif age <= 180:
                    age_bucket = "91-180d"
                elif age <= 365:
                    age_bucket = "181-365d"
                else:
                    age_bucket = ">365d"
                age_counts[age_bucket] += 1

                if not isinstance(apply_url, str) or not apply_url.strip():
                    apply_url = None
                    missing_apply += 1

                public_probe = _probe(client, listing.url, delay=max(0.0, args.delay))
                apply_probe = _probe(client, apply_url, delay=max(0.0, args.delay))
                state = _overall_state(public_probe, apply_probe)
                state_counts[state] += 1
                checked += 1

                suspicious_age = age is None or age > 180
                suspicious = (
                    state != "live_confirmed"
                    or suspicious_age
                    or apply_url is None
                )
                if not args.all and not suspicious:
                    continue

                title = listing.job.title or "<missing-title>"
                tenant = _tenant(payload)
                released_text = str(released) if released else "-"
                age_text = str(age) if age is not None else "-"
                print(f"[{state}] [{tenant}] {title}")
                print(
                    f"  released={released_text} age_days={age_text} "
                    f"{_format_probe('public', public_probe)} "
                    f"{_format_probe('apply', apply_probe)}"
                )
                print(f"  public_url={listing.url}")
                if apply_url:
                    print(f"  apply_url={apply_url}")
                if public_probe.final_url and public_probe.final_url != listing.url:
                    print(f"  public_final={public_probe.final_url}")
                if apply_probe.final_url and apply_url and apply_probe.final_url != apply_url:
                    print(f"  apply_final={apply_probe.final_url}")
                if public_probe.error:
                    print(f"  public_error={public_probe.error}")
                if apply_probe.error:
                    print(f"  apply_error={apply_probe.error}")

        print("summary:")
        print(f"  checked={checked}")
        for state, count in sorted(state_counts.items()):
            print(f"  state[{state}]={count}")
        for bucket in ("0-30d", "31-90d", "91-180d", "181-365d", ">365d", "unknown"):
            if age_counts[bucket]:
                print(f"  released_age[{bucket}]={age_counts[bucket]}")
        print(f"  missing_apply_url={missing_apply}")
        print("note=age alone is not closure; HTTP/closed-page evidence is reported separately")


if __name__ == "__main__":
    main()
