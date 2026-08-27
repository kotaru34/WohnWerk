from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import SessionLocal
from app.models import CrawlRun, Job, JobListing, ListingStatus, Source


def _is_relevant(listing: JobListing) -> bool:
    payload = listing.raw_payload or {}
    gate = payload.get("wohnwerk_discovery_gate")
    return isinstance(gate, dict) and gate.get("accepted") is True


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

        source_active = [listing for listing in listings if listing.status == ListingStatus.ACTIVE]
        relevant_active = [listing for listing in source_active if _is_relevant(listing)]
        source_active_jobs = {listing.job_id: listing.job for listing in source_active}
        relevant_jobs = {listing.job_id: listing.job for listing in relevant_active}
        jobs = list(relevant_jobs.values())

        current_source_sightings = (
            [listing for listing in listings if listing.last_seen_crawl_run_id == latest_run.id]
            if latest_run is not None
            else []
        )
        current_relevant = [listing for listing in current_source_sightings if _is_relevant(listing)]

        source_tenant_counts: Counter[str] = Counter()
        relevant_tenant_counts: Counter[str] = Counter()
        for listing in source_active:
            payload = listing.raw_payload or {}
            region = payload.get("wohnwerk_lever_region") or "unknown"
            site = payload.get("wohnwerk_lever_site") or "unknown"
            tenant = f"{region}:{site}"
            source_tenant_counts[tenant] += 1
            if _is_relevant(listing):
                relevant_tenant_counts[tenant] += 1

        current_titles: dict[str, list[str]] = defaultdict(list)
        for listing in current_relevant:
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
            f"listings_total={len(listings)} source_active_listings={len(source_active)} "
            f"relevant_active_listings={len(relevant_active)}"
        )
        print(
            f"source_active_canonical_jobs={len(source_active_jobs)} "
            f"relevant_active_canonical_jobs={len(relevant_jobs)}"
        )
        if latest_run is not None:
            print(
                f"latest_run={latest_run.id} "
                f"current_run_source_sightings={len(current_source_sightings)} "
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
        for tenant, count in sorted(source_tenant_counts.items()):
            print(f"  {tenant}: {count}")

        print("tenants_relevant_active:")
        for tenant, count in sorted(relevant_tenant_counts.items()):
            print(f"  {tenant}: {count}")

        if current_titles:
            print("current_run_relevant_title_samples:")
            for tenant in sorted(current_titles):
                print(f"  [{tenant}]")
                for title in current_titles[tenant][:15]:
                    print(f"    - {title}")
                remaining = len(current_titles[tenant]) - 15
                if remaining > 0:
                    print(f"    ... {remaining} more")

        if unresolved_counts:
            print("relevant_unresolved_location_texts:")
            for text, count in unresolved_counts.most_common(30):
                print(f"  {count}x {text}")


if __name__ == "__main__":
    main()
