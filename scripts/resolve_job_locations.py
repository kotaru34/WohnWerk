from __future__ import annotations

from collections import Counter

from sqlalchemy import exists, func, or_, select

from app.database import SessionLocal
from app.jobs.jobs_at_location_repair import repair_unresolved_jobs_at_locations
from app.jobs.location_cleanup import prune_redundant_country_code_locations
from app.jobs.location_resolution import canonicalize_locality, resolve_localities
from app.jobs.location_resolution_fallback import resolve_localities_full_scan
from app.models import JobListing, JobLocation, ListingStatus, Source


def _resolution_label(location: JobLocation) -> str | None:
    if location.city and location.city.strip():
        return location.city.strip()

    # Some source adapters preserve a concrete locality only in the raw location text.
    # Reuse it for geocoding without pretending that we received a structured city field.
    text = (location.location_text or "").strip()
    if not text or canonicalize_locality(text) is None:
        return None
    return text


def _has_active_german_source():
    # Existing v1 sources have no country_code and are intentionally interpreted as AT.
    source_country = func.upper(func.coalesce(Source.config["country_code"].astext, "AT"))
    return exists(
        select(JobListing.id)
        .join(Source, Source.id == JobListing.source_id)
        .where(
            JobListing.job_id == JobLocation.job_id,
            JobListing.status == ListingStatus.ACTIVE,
            source_country == "DE",
        )
    )


def main() -> None:
    with SessionLocal() as session:
        source_repair = repair_unresolved_jobs_at_locations(session)
        redundant_country_codes_removed = prune_redundant_country_code_locations(session)

        # This resolver is deliberately Austria-specific. German jobs are resolved by
        # their five-digit PLZ at ingest time or by explicit source WGS84 coordinates.
        # Excluding every canonical job with an active DE listing prevents same-named
        # German localities from ever being mapped to an Austrian postal centroid.
        locations = list(
            session.scalars(
                select(JobLocation)
                .where(
                    JobLocation.location.is_(None),
                    ~_has_active_german_source(),
                    or_(
                        JobLocation.city.is_not(None),
                        JobLocation.location_text.is_not(None),
                    ),
                )
                .order_by(JobLocation.id)
            )
        )

        labels_by_location = {location.id: _resolution_label(location) for location in locations}
        labels = {label for label in labels_by_location.values() if label is not None}
        resolutions = resolve_localities(session, labels)

        # The normal resolver deliberately uses a narrow SQL prefix prefilter. Punctuation
        # such as `St. Valentin`, official-vs-source `Sankt` spelling, small
        # Statistics-Austria-backed locality exceptions and a tiny verified sublocality
        # table therefore use one in-memory scan of the Austrian postal table. Matching
        # never becomes fuzzy.
        missing_labels = {label for label in labels if label not in resolutions}
        if missing_labels:
            resolutions.update(resolve_localities_full_scan(session, missing_labels))

        updated = 0
        unresolved: Counter[str] = Counter()
        resolved: Counter[str] = Counter()
        skipped_without_concrete_label = 0

        for location in locations:
            label = labels_by_location[location.id]
            if label is None:
                skipped_without_concrete_label += 1
                unresolved[
                    (location.city or location.location_text or "<missing>").strip()
                    or "<missing>"
                ] += 1
                continue

            resolution = resolutions.get(label)
            if resolution is None:
                unresolved[label] += 1
                continue

            location.location = resolution.as_wkt()
            updated += 1
            resolved[f"{label} -> {resolution.canonical_locality} [{resolution.method}]"] += 1

        session.commit()

        print(
            "jobs_at_source_repair="
            f"considered:{source_repair.considered} "
            f"repaired:{source_repair.repaired} "
            f"unresolved:{source_repair.unresolved} "
            f"failed:{source_repair.failed}"
        )
        print(f"redundant_country_code_locations_removed={redundant_country_codes_removed}")
        print(
            f"location_candidates={len(locations)} resolved={updated} "
            f"unresolved={len(locations) - updated} "
            f"without_concrete_label={skipped_without_concrete_label}"
        )
        if resolved:
            print("resolved_localities:")
            for label, count in sorted(resolved.items()):
                print(f"  {count}x {label}")
        if unresolved:
            print("unresolved_localities:")
            for label, count in unresolved.most_common(30):
                print(f"  {count}x {label}")


if __name__ == "__main__":
    main()
