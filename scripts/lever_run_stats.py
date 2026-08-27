from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import CrawlRun, Job, JobListing, ListingStatus, Source


def main() -> None:
    with SessionLocal() as session:
        source = session.scalar(select(Source).where(Source.name == "lever-public-postings"))
        if source is None:
            print("lever-public-postings source not configured")
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

        active = [listing for listing in listings if listing.status == ListingStatus.ACTIVE]
        active_jobs = {listing.job_id: listing.job for listing in active}
        jobs = list(active_jobs.values())
        current_run = (
            [listing for listing in listings if listing.last_seen_crawl_run_id == latest_run.id]
            if latest_run is not None
            else []
        )

        tenant_counts: Counter[str] = Counter()
        for listing in active:
            payload = listing.raw_payload or {}
            region = payload.get("wohnwerk_lever_region") or "unknown"
            site = payload.get("wohnwerk_lever_site") or "unknown"
            tenant_counts[f"{region}:{site}"] += 1

        current_titles: dict[str, list[str]] = defaultdict(list)
        for listing in current_run:
            payload = listing.raw_payload or {}
            region = payload.get("wohnwerk_lever_region") or "unknown"
            site = payload.get("wohnwerk_lever_site") or "unknown"
            tenant = f"{region}:{site}"
            if listing.job.title and listing.job.title not in current_titles[tenant]:
                current_titles[tenant].append(listing.job.title)

        locations = [location for job in jobs for location in job.locations]
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

        print(f"source_enabled={source.enabled} coverage={source.coverage_status}")
        print(
            f"listings_total={len(listings)} active_listings={len(active)} "
            f"active_canonical_jobs={len(jobs)}"
        )
        if latest_run is not None:
            print(
                f"latest_run={latest_run.id} "
                f"current_run_accepted_listings={len(current_run)}"
            )
        print(
            f"locations={len(locations)} geo_resolved={len(geo_resolved)} "
            f"postal_resolved={len(postal_resolved)} city_approx={len(city_approx)} "
            f"unresolved={len(locations) - len(geo_resolved)}"
        )
        print(
            f"salary_structured={len(structured_salary)} salary_text={len(raw_salary_text)} "
            f"salary_annualized={len(annualized_salary)}"
        )

        print("tenants_active_source_history:")
        for tenant, count in sorted(tenant_counts.items()):
            print(f"  {tenant}: {count}")

        if current_titles:
            print("current_run_accepted_title_samples:")
            for tenant in sorted(current_titles):
                print(f"  [{tenant}]")
                for title in current_titles[tenant][:15]:
                    print(f"    - {title}")
                remaining = len(current_titles[tenant]) - 15
                if remaining > 0:
                    print(f"    ... {remaining} more")

        if unresolved_counts:
            print("unresolved_location_texts:")
            for text, count in unresolved_counts.most_common(30):
                print(f"  {count}x {text}")


if __name__ == "__main__":
    main()
