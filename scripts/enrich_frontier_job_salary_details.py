from __future__ import annotations

import argparse
import time
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import Job, JobListing, ListingStatus, Source
from app.sources.job.detail_salary import parse_salary_detail_html

SOURCE_PREFIXES = {
    "stepstone.at": "stepstoneat:",
    "willhaben-jobs": "willhabenjobs:",
}
POLICY = "frontier-explicit-detail-salary-2026-08-29-v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch source detail pages and backfill only explicit, parseable salary facts."
    )
    parser.add_argument("--source", choices=sorted(SOURCE_PREFIXES), required=True)
    parser.add_argument(
        "--id",
        action="append",
        default=[],
        help="Source listing id or numeric board id. Repeat for multiple exact listings.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="When --id is omitted, inspect at most this many missing-salary listings.",
    )
    parser.add_argument("--delay", type=float, default=0.75)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _normalized_ids(source_name: str, values: list[str]) -> list[str]:
    prefix = SOURCE_PREFIXES[source_name]
    output: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        normalized = cleaned if cleaned.startswith(prefix) else prefix + cleaned
        if normalized not in output:
            output.append(normalized)
    return output


def _annual_value(
    value: Decimal | None,
    *,
    period: str,
    payment_count: int | None,
) -> Decimal | None:
    if value is None:
        return None
    if period == "year":
        return value
    if period == "month" and payment_count:
        return value * payment_count
    return None


def _conflict(job: Job, parsed) -> str | None:
    if job.salary_min is not None and job.salary_min != parsed.minimum:
        return f"existing minimum {job.salary_min} != parsed {parsed.minimum}"
    if job.salary_max is not None and parsed.maximum is not None and job.salary_max != parsed.maximum:
        return f"existing maximum {job.salary_max} != parsed {parsed.maximum}"
    if job.salary_currency and job.salary_currency.upper() != parsed.currency:
        return f"existing currency {job.salary_currency} != parsed {parsed.currency}"
    if job.salary_period and job.salary_period.lower() != parsed.period:
        return f"existing period {job.salary_period} != parsed {parsed.period}"
    return None


def _apply(job: Job, listing: JobListing, parsed) -> None:
    job.salary_text = parsed.text
    job.salary_min = parsed.minimum
    if parsed.maximum is not None:
        job.salary_max = parsed.maximum
    job.salary_currency = parsed.currency
    job.salary_period = parsed.period
    if parsed.payment_count is not None:
        job.salary_payment_count = parsed.payment_count
    job.salary_provenance = "TEXT_EXPLICIT"
    job.salary_confidence = parsed.confidence
    job.salary_is_minimum_only = parsed.minimum_only

    annual_min = _annual_value(
        parsed.minimum,
        period=parsed.period,
        payment_count=parsed.payment_count,
    )
    annual_max = _annual_value(
        parsed.maximum,
        period=parsed.period,
        payment_count=parsed.payment_count,
    )
    if annual_min is not None:
        job.salary_min_eur_year = annual_min
    if annual_max is not None:
        job.salary_max_eur_year = annual_max

    payload = dict(listing.raw_payload or {})
    payload["detail_enriched"] = True
    payload["detail_salary_backfill_policy"] = POLICY
    payload["detail_salary_text"] = parsed.text
    listing.raw_payload = payload


def main() -> None:
    args = parse_args()
    selected_ids = _normalized_ids(args.source, args.id)
    limit = max(1, args.limit)
    delay = max(0.0, args.delay)

    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == args.source))
        if source is None:
            raise SystemExit(f"source not found: {args.source}")

        stmt = (
            select(JobListing)
            .where(
                JobListing.source_id == source.id,
                JobListing.status == ListingStatus.ACTIVE,
            )
            .options(selectinload(JobListing.job))
            .order_by(JobListing.id)
        )
        if selected_ids:
            stmt = stmt.where(JobListing.source_listing_id.in_(selected_ids))
        else:
            stmt = stmt.join(Job, Job.id == JobListing.job_id).where(Job.salary_min.is_(None)).limit(limit)

        listings = list(session.scalars(stmt))
        found_ids = {listing.source_listing_id for listing in listings}
        missing_ids = [value for value in selected_ids if value not in found_ids]
        if missing_ids:
            print("missing_listing_ids=" + ",".join(missing_ids))

        parsed_count = 0
        conflicts = 0
        failures = len(missing_ids)
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"mode={mode} source={args.source} listings={len(listings)}")

        with httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
                "User-Agent": "WohnWerk/0.2 (+private self-hosted Austrian job search)",
            },
        ) as client:
            for index, listing in enumerate(listings):
                if index and delay:
                    time.sleep(delay)
                try:
                    response = client.get(listing.url)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    print(
                        f"ERROR listing={listing.source_listing_id} job={listing.job_id} "
                        f"fetch={type(exc).__name__}: {exc}"
                    )
                    failures += 1
                    continue

                parsed = parse_salary_detail_html(response.text)
                if parsed is None:
                    print(
                        f"NO-SALARY listing={listing.source_listing_id} job={listing.job_id} "
                        f"url={listing.url}"
                    )
                    failures += 1
                    continue

                conflict = _conflict(listing.job, parsed)
                if conflict:
                    print(
                        f"CONFLICT listing={listing.source_listing_id} job={listing.job_id} "
                        f"reason={conflict} evidence={parsed.text!r}"
                    )
                    conflicts += 1
                    continue

                parsed_count += 1
                print(
                    f"OK listing={listing.source_listing_id} job={listing.job_id} "
                    f"min={parsed.minimum} max={parsed.maximum} currency={parsed.currency} "
                    f"period={parsed.period} minimum_only={parsed.minimum_only} "
                    f"payments={parsed.payment_count} evidence={parsed.text!r}"
                )
                if args.apply:
                    _apply(listing.job, listing, parsed)

        if args.apply and conflicts == 0 and failures == 0:
            session.commit()
        elif args.apply:
            session.rollback()
            print("apply_rolled_back=true")

        print(
            f"parsed={parsed_count} conflicts={conflicts} failures={failures} "
            f"committed={args.apply and conflicts == 0 and failures == 0}"
        )
        if conflicts or failures:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
