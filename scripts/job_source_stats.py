from __future__ import annotations

import argparse
from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import CrawlRun, Job, JobListing, ListingStatus, Source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show job-source lifecycle/relevance diagnostics.")
    parser.add_argument("source", help="Source name, e.g. personio-public-xml")
    parser.add_argument(
        "--all-titles",
        action="store_true",
        help="Print every unique current-run relevant title instead of compact samples.",
    )
    return parser.parse_args()


def _gate_accepted(listing: JobListing) -> bool:
    payload = listing.raw_payload or {}
    gate = payload.get("wohnwerk_discovery_gate")
    return isinstance(gate, dict) and gate.get("accepted") is True


def _tenant_label(payload: dict) -> str:
    lever_site = payload.get("wohnwerk_lever_site")
    if lever_site:
        region = payload.get("wohnwerk_lever_region") or "unknown"
        return f"{region}:{lever_site}"
    personio = payload.get("wohnwerk_personio_tenant")
    if personio:
        return str(personio)
    smartrecruiters = payload.get("wohnwerk_smartrecruiters_tenant")
    if smartrecruiters:
        return str(smartrecruiters)
    return "unknown"


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == args.source))
        if source is None:
            print(f"source_not_found={args.source}")
            return

        latest_run = session.scalar(
            select(CrawlRun)
            .where(CrawlRun.source_id == source.id)
            .order_by(CrawlRun.started_at.desc())
            .limit(1)
        )
        listings = list(
            session.scalars(
                select(JobListing)
                .where(JobListing.source_id == source.id)
                .options(selectinload(JobListing.job).selectinload(Job.locations))
                .order_by(JobListing.id)
            )
        )

        source_active = [row for row in listings if row.status == ListingStatus.ACTIVE]
        relevant_active = [row for row in source_active if _gate_accepted(row)]
        source_jobs = {row.job_id: row.job for row in source_active}
        relevant_jobs = {row.job_id: row.job for row in relevant_active}

        current_source = (
            [row for row in listings if row.last_seen_crawl_run_id == latest_run.id]
            if latest_run is not None
            else []
        )
        current_relevant = [row for row in current_source if _gate_accepted(row)]

        source_tenants: Counter[str] = Counter()
        relevant_tenants: Counter[str] = Counter()
        current_titles: dict[str, list[str]] = defaultdict(list)

        for listing in source_active:
            source_tenants[_tenant_label(listing.raw_payload or {})] += 1
        for listing in relevant_active:
            relevant_tenants[_tenant_label(listing.raw_payload or {})] += 1
        for listing in current_relevant:
            tenant = _tenant_label(listing.raw_payload or {})
            if listing.job.title and listing.job.title not in current_titles[tenant]:
                current_titles[tenant].append(listing.job.title)

        locations = [location for job in relevant_jobs.values() for location in job.locations]
        postal_resolved = [location for location in locations if location.postal_code]
        geo_resolved = [location for location in locations if location.location is not None]
        city_approx = [
            location
            for location in geo_resolved
            if location.postal_code is None and location.city is not None
        ]
        unresolved = [
            location.location_text
            for location in locations
            if location.location is None and location.location_text
        ]
        unresolved_counts = Counter(unresolved)

        jobs = list(relevant_jobs.values())
        structured_salary = [
            job
            for job in jobs
            if job.salary_min is not None
            or job.salary_max is not None
            or job.salary_currency is not None
        ]
        annualized_salary = [
            job
            for job in jobs
            if job.salary_min_eur_year is not None or job.salary_max_eur_year is not None
        ]
        raw_salary_text = [job for job in jobs if job.salary_text]

        print(f"source={source.name} enabled={source.enabled} coverage={source.coverage_status}")
        print(
            f"listings_total={len(listings)} source_active_listings={len(source_active)} "
            f"relevant_active_listings={len(relevant_active)}"
        )
        print(
            f"source_active_canonical_jobs={len(source_jobs)} "
            f"relevant_active_canonical_jobs={len(relevant_jobs)}"
        )
        if latest_run is not None:
            print(
                f"latest_run={latest_run.id} current_run_source_sightings={len(current_source)} "
                f"current_run_relevant={len(current_relevant)}"
            )
        print(
            f"relevant_locations={len(locations)} geo_resolved={len(geo_resolved)} "
            f"postal_resolved={len(postal_resolved)} city_approx={len(city_approx)} "
            f"unresolved={len(locations) - len(geo_resolved)}"
        )
        print(
            f"relevant_salary_structured={len(structured_salary)} "
            f"relevant_salary_text={len(raw_salary_text)} "
            f"relevant_salary_annualized={len(annualized_salary)}"
        )

        print("tenants_source_active:")
        for tenant, count in sorted(source_tenants.items()):
            print(f"  {tenant}: {count}")
        print("tenants_relevant_active:")
        for tenant, count in sorted(relevant_tenants.items()):
            print(f"  {tenant}: {count}")

        if current_titles:
            heading = (
                "current_run_relevant_titles:"
                if args.all_titles
                else "current_run_relevant_title_samples:"
            )
            print(heading)
            for tenant in sorted(current_titles):
                print(f"  [{tenant}]")
                titles = current_titles[tenant]
                shown = titles if args.all_titles else titles[:20]
                for title in shown:
                    print(f"    - {title}")
                if not args.all_titles:
                    remaining = len(titles) - len(shown)
                    if remaining > 0:
                        print(f"    ... {remaining} more")

        if unresolved_counts:
            print("unresolved_location_texts:")
            for text, count in unresolved_counts.most_common(30):
                print(f"  {count}x {text}")


if __name__ == "__main__":
    main()
