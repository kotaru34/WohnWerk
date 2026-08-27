from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.jobs.location_resolution import LocalityResolution, resolve_localities
from app.models import CrawlRun, Job, JobListing, JobLocation, ListingStatus, PostalCode, Source
from app.sources.base import RawJob, RawJobLocation


def _listing_payload(
    item: RawJob,
    *,
    known_postal: dict[str, PostalCode],
    locality_resolutions: dict[str, LocalityResolution],
) -> dict:
    payload = dict(item.raw_payload)
    resolution_rows: list[dict] = []
    for location in item.locations:
        postal = known_postal.get(location.postal_code or "")
        locality = locality_resolutions.get(location.city or "")
        row = {
            "source_postal_code": location.postal_code,
            "postal_code_resolved": postal is not None,
            "city": location.city,
            "location_text": location.location_text,
            "remote": location.remote,
            "location_resolved": postal is not None or locality is not None,
        }
        if locality is not None and postal is None:
            row.update(
                {
                    "resolution_method": locality.method,
                    "resolution_source": locality.source,
                    "canonical_locality": locality.canonical_locality,
                    "matched_postal_codes": list(locality.postal_codes),
                    "address_sample_count": locality.address_sample_count,
                }
            )
        resolution_rows.append(row)

    payload["wohnwerk_location_resolution"] = resolution_rows
    return payload


def _merge_listing_payload(existing_payload: dict | None, incoming_payload: dict) -> dict:
    """Merge sparse job discovery without discarding prior enrichment."""
    existing = dict(existing_payload or {})
    merged = dict(existing)
    merged.update(incoming_payload)

    previous_enriched = existing.get("detail_enriched") is True
    incoming_enriched = incoming_payload.get("detail_enriched")

    if previous_enriched and incoming_enriched is not True:
        merged["detail_enriched"] = True
        transient_error = incoming_payload.get("detail_enrichment_error")
        if transient_error:
            merged["detail_enrichment_last_error"] = transient_error
        merged.pop("detail_enrichment_error", None)
    elif incoming_enriched is True:
        merged.pop("detail_enrichment_error", None)
        merged.pop("detail_enrichment_last_error", None)

    return merged


def _annual_eur_value(
    value: Decimal | None,
    *,
    currency: str | None,
    period: str | None,
    payment_count: int | None,
) -> Decimal | None:
    """Annualize only when the source gives enough explicit semantics.

    In particular, monthly Austrian salary is not blindly multiplied by 14. A monthly
    value is annualized only when the source explicitly supplies the payment count.
    """
    if value is None or not currency or not period:
        return None
    if currency.upper() != "EUR":
        return None

    normalized_period = period.lower()
    if normalized_period == "year":
        return value
    if normalized_period == "month" and payment_count is not None and payment_count > 0:
        return value * payment_count
    return None


def _enrich_salary(job_row: Job, item: RawJob) -> None:
    if item.salary_text is not None:
        job_row.salary_text = item.salary_text
    if item.salary_min is not None:
        job_row.salary_min = item.salary_min
    if item.salary_max is not None:
        job_row.salary_max = item.salary_max
    if item.salary_currency is not None:
        job_row.salary_currency = item.salary_currency.upper()
    if item.salary_period is not None:
        job_row.salary_period = item.salary_period.lower()
    if item.salary_payment_count is not None:
        job_row.salary_payment_count = item.salary_payment_count
    if item.salary_provenance is not None:
        job_row.salary_provenance = item.salary_provenance
    if item.salary_confidence is not None:
        job_row.salary_confidence = item.salary_confidence
    if item.salary_is_minimum_only is not None:
        job_row.salary_is_minimum_only = item.salary_is_minimum_only

    annual_min = _annual_eur_value(
        item.salary_min,
        currency=item.salary_currency,
        period=item.salary_period,
        payment_count=item.salary_payment_count,
    )
    annual_max = _annual_eur_value(
        item.salary_max,
        currency=item.salary_currency,
        period=item.salary_period,
        payment_count=item.salary_payment_count,
    )
    if annual_min is not None:
        job_row.salary_min_eur_year = annual_min
    if annual_max is not None:
        job_row.salary_max_eur_year = annual_max


def _normalized_location_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split()).casefold()
    return normalized or None


def _location_key(
    *,
    postal_code: str | None,
    city: str | None,
    location_text: str | None,
    remote: bool,
) -> tuple[str | None, str | None, str | None, bool]:
    return (
        postal_code,
        _normalized_location_text(city),
        _normalized_location_text(location_text),
        remote,
    )


def _enrich_locations(
    job_row: Job,
    *,
    locations: list[RawJobLocation],
    known_postal: dict[str, PostalCode],
    locality_resolutions: dict[str, LocalityResolution],
) -> None:
    """Add/enrich locations without erasing richer locations from another source."""
    existing_by_key = {
        _location_key(
            postal_code=location.postal_code,
            city=location.city,
            location_text=location.location_text,
            remote=location.remote,
        ): location
        for location in job_row.locations
    }

    for item in locations:
        postal = known_postal.get(item.postal_code or "")
        postal_code = postal.postal_code if postal is not None else None
        locality = locality_resolutions.get(item.city or "") if not item.remote else None
        key = _location_key(
            postal_code=postal_code,
            city=item.city,
            location_text=item.location_text,
            remote=item.remote,
        )
        existing = existing_by_key.get(key)
        if existing is not None:
            if existing.location is None:
                if postal is not None:
                    existing.location = postal.location
                elif locality is not None:
                    existing.location = locality.as_wkt()
            continue

        # If an earlier sparse source could only preserve the human-readable location,
        # enrich that row with the PLZ centroid rather than creating a duplicate.
        unresolved_key = _location_key(
            postal_code=None,
            city=item.city,
            location_text=item.location_text,
            remote=item.remote,
        )
        unresolved = existing_by_key.get(unresolved_key)
        if unresolved is not None and postal is not None:
            unresolved.postal_code = postal.postal_code
            unresolved.location = postal.location
            existing_by_key.pop(unresolved_key, None)
            existing_by_key[key] = unresolved
            continue

        location_row = JobLocation(
            postal_code=postal_code,
            city=item.city,
            location_text=item.location_text,
            location=(
                postal.location
                if postal is not None
                else locality.as_wkt()
                if locality is not None
                else None
            ),
            remote=item.remote,
        )
        job_row.locations.append(location_row)
        existing_by_key[key] = location_row


def _enrich_job(
    job_row: Job,
    *,
    item: RawJob,
    known_postal: dict[str, PostalCode],
    locality_resolutions: dict[str, LocalityResolution],
    now: datetime,
) -> None:
    if item.title:
        job_row.title = item.title
    if item.company is not None:
        job_row.company = item.company
    if item.description is not None:
        job_row.description = item.description

    _enrich_salary(job_row, item)
    if item.locations:
        _enrich_locations(
            job_row,
            locations=item.locations,
            known_postal=known_postal,
            locality_resolutions=locality_resolutions,
        )

    job_row.status = ListingStatus.ACTIVE
    job_row.last_seen_at = now
    job_row.inactive_at = None


def ingest_jobs(
    session: Session,
    *,
    source: Source,
    run: CrawlRun,
    items: list[RawJob],
) -> tuple[int, int]:
    """Persist job discovery with enrichment-only updates and exact-URL deduplication."""
    if not items:
        return 0, 0

    now = datetime.now(UTC)
    postal_codes = {
        location.postal_code
        for item in items
        for location in item.locations
        if location.postal_code
    }
    known_postal = {
        row.postal_code: row
        for row in session.scalars(
            select(PostalCode).where(PostalCode.postal_code.in_(postal_codes))
        )
    }
    city_labels = {
        location.city
        for item in items
        for location in item.locations
        if location.city and not location.remote
    }
    locality_resolutions = resolve_localities(session, city_labels)

    source_ids = [item.source_listing_id for item in items]
    existing = {
        listing.source_listing_id: listing
        for listing in session.scalars(
            select(JobListing).where(
                JobListing.source_id == source.id,
                JobListing.source_listing_id.in_(source_ids),
            )
        )
    }

    urls = {item.url for item in items}
    exact_url_jobs: dict[str, Job] = {}
    if urls:
        for listing in session.scalars(
            select(JobListing).where(JobListing.url.in_(urls)).order_by(JobListing.id)
        ):
            exact_url_jobs.setdefault(listing.url, listing.job)

    new_count = 0
    updated_count = 0

    for item in items:
        listing = existing.get(item.source_listing_id)
        payload = _listing_payload(
            item,
            known_postal=known_postal,
            locality_resolutions=locality_resolutions,
        )

        if listing is None:
            job_row = exact_url_jobs.get(item.url)
            if job_row is None:
                job_row = Job(
                    title=item.title,
                    company=item.company,
                    description=item.description,
                    salary_text=item.salary_text,
                    status=ListingStatus.ACTIVE,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                session.add(job_row)
                _enrich_salary(job_row, item)
                _enrich_locations(
                    job_row,
                    locations=item.locations,
                    known_postal=known_postal,
                    locality_resolutions=locality_resolutions,
                )
                session.flush()
            else:
                _enrich_job(
                    job_row,
                    item=item,
                    known_postal=known_postal,
                    locality_resolutions=locality_resolutions,
                    now=now,
                )

            exact_url_jobs[item.url] = job_row
            listing = JobListing(
                job_id=job_row.id,
                source_id=source.id,
                source_listing_id=item.source_listing_id,
                url=item.url,
                status=ListingStatus.ACTIVE,
                raw_payload=payload,
                last_seen_crawl_run_id=run.id,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(listing)
            existing[item.source_listing_id] = listing
            new_count += 1
            continue

        job_row = listing.job
        _enrich_job(
            job_row,
            item=item,
            known_postal=known_postal,
            locality_resolutions=locality_resolutions,
            now=now,
        )
        listing.url = item.url
        listing.status = ListingStatus.ACTIVE
        listing.raw_payload = _merge_listing_payload(listing.raw_payload, payload)
        listing.last_seen_crawl_run_id = run.id
        listing.last_seen_at = now
        listing.inactive_at = None
        exact_url_jobs[item.url] = job_row
        updated_count += 1

    session.commit()
    return new_count, updated_count
