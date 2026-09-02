from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.ingestion.jobs import _annual_eur_value
from app.jobs.fit_store import annual_salary_label
from app.jobs.salary import ParsedSalary, parse_salary_text
from app.models import Job, ListingStatus


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse explicit salary statements already stored in active job text. "
            "Dry-run by default; this command performs no network requests."
        )
    )
    parser.add_argument("--apply", action="store_true", help="Persist safe missing salary fields.")
    parser.add_argument("--sample", type=int, default=30, help="Maximum candidate samples to print.")
    return parser.parse_args()


def _candidate(job: Job) -> ParsedSalary | None:
    # A complete source-structured salary already has better provenance than text parsing.
    if job.salary_min is not None and job.salary_currency and job.salary_period:
        return None
    return parse_salary_text(job.salary_text, trusted=True) or parse_salary_text(job.description)


def _compatible(job: Job, parsed: ParsedSalary) -> bool:
    if job.salary_min is not None and job.salary_min != parsed.minimum:
        return False
    if job.salary_max is not None and (
        parsed.maximum is None or job.salary_max != parsed.maximum
    ):
        return False
    if job.salary_currency is not None and job.salary_currency.upper() != parsed.currency:
        return False
    return job.salary_period is None or job.salary_period.lower() == parsed.period


def _apply(job: Job, parsed: ParsedSalary) -> None:
    if job.salary_min is None:
        job.salary_min = parsed.minimum
    if job.salary_max is None and parsed.maximum is not None:
        job.salary_max = parsed.maximum
    if job.salary_currency is None:
        job.salary_currency = parsed.currency
    if job.salary_period is None:
        job.salary_period = parsed.period
    if job.salary_payment_count is None and parsed.payment_count is not None:
        job.salary_payment_count = parsed.payment_count
    if job.salary_provenance is None:
        job.salary_provenance = "TEXT_EXPLICIT"
    if job.salary_confidence is None:
        job.salary_confidence = parsed.confidence
    if job.salary_is_minimum_only is None:
        job.salary_is_minimum_only = parsed.minimum_only
    if job.salary_text is None:
        job.salary_text = parsed.text

    annual_min = _annual_eur_value(
        job.salary_min,
        currency=job.salary_currency,
        period=job.salary_period,
        payment_count=job.salary_payment_count,
    )
    annual_max = _annual_eur_value(
        job.salary_max,
        currency=job.salary_currency,
        period=job.salary_period,
        payment_count=job.salary_payment_count,
    )
    if annual_min is not None and job.salary_min_eur_year is None:
        job.salary_min_eur_year = annual_min
    if annual_max is not None and job.salary_max_eur_year is None:
        job.salary_max_eur_year = annual_max


def _money(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return f"{value:f}"


def main() -> None:
    args = parse_args()
    sample_limit = max(0, args.sample)

    with SessionLocal() as session:
        jobs = list(
            session.scalars(
                select(Job)
                .where(Job.status == ListingStatus.ACTIVE)
                .order_by(Job.id)
            )
        )

        period_counts: Counter[str] = Counter()
        candidates: list[tuple[Job, ParsedSalary]] = []
        conflicts = 0
        already_structured = 0

        for job in jobs:
            if job.salary_min is not None and job.salary_currency and job.salary_period:
                already_structured += 1
                continue
            parsed = _candidate(job)
            if parsed is None:
                continue
            if not _compatible(job, parsed):
                conflicts += 1
                continue
            candidates.append((job, parsed))
            period_counts[parsed.period] += 1

        print(f"active_jobs={len(jobs)}")
        print(f"already_structured={already_structured}")
        print(f"candidates={len(candidates)}")
        print(f"conflicts_skipped={conflicts}")
        print("candidate_periods:")
        for period, count in sorted(period_counts.items()):
            print(f"  {period}={count}")

        if sample_limit and candidates:
            print("sample:")
            for job, parsed in candidates[:sample_limit]:
                preview = Job(
                    title=job.title,
                    salary_min=job.salary_min or parsed.minimum,
                    salary_max=job.salary_max if job.salary_max is not None else parsed.maximum,
                    salary_currency=job.salary_currency or parsed.currency,
                    salary_period=job.salary_period or parsed.period,
                    salary_payment_count=job.salary_payment_count or parsed.payment_count,
                    salary_is_minimum_only=(
                        job.salary_is_minimum_only
                        if job.salary_is_minimum_only is not None
                        else parsed.minimum_only
                    ),
                )
                print(
                    f"  job={job.id} period={parsed.period} "
                    f"min={_money(parsed.minimum)} max={_money(parsed.maximum)} "
                    f"payments={parsed.payment_count or '-'} "
                    f"label={annual_salary_label(preview)!r} "
                    f"title={job.title!r}"
                )
                print(f"    evidence={parsed.text!r}")

        if not args.apply:
            print("mode=dry-run no database changes")
            return

        for job, parsed in candidates:
            _apply(job, parsed)
        session.commit()
        print(f"updated={len(candidates)}")
        print("mode=applied")


if __name__ == "__main__":
    main()
