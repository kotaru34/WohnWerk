from __future__ import annotations

from collections import Counter

from sqlalchemy import or_, select

from app.database import SessionLocal
from app.jobs.jobs_at_location_repair import repair_unresolved_jobs_at_locations
from app.jobs.location_resolution import canonicalize_locality, resolve_localities
from app.jobs.location_resolution_fallback import resolve_localities_full_scan
from app.models import JobLocation


def _resolution_label(location: JobLocation) -> str | None:
    if location.city and location.city.strip():
        return location.city.strip()

    # Some source adapters preserve a concrete locality only in the raw location text.
    # Reuse it for geocoding without pretending that we received a structured city field.
    text = (location.location_text or "").strip()
    if not text or canonicalize_locality(text) is None:
        return None
    return text


def main() -> None:
    with SessionLocal() as session:
        source_repair = repair_unresolved_jobs_at_locations(session)

        # Remote-capable jobs can still have a real source-provided locality. Preserve the
        # remote flag, but resolve that physical place just like an on-site vacancy. For a
        # few adapters the concrete locality exists only in location_text; countrywide and
        # Bundesland-only labels remain excluded by canonicalize_locality()/the resolver.
        locations = list(
            session.scalars(
                select(JobLocation)
                .where(
                    JobLocation.location.is_(None),
                    or_(
                        JobLocation.city.is_not(None),
                        JobLocation.location_text.is_not(None),
                    ),
                )
                .order_by(JobLocation.id)
            )
        )

        labels_by_location = {
            location.id: _resolution_label(location)
            for location in locations
        }
        labels = {
            label
            for label in labels_by_location.values()
            if label is not None
        }
        resolutions = resolve_localities(session, labels)

        # The normal resolver deliberately uses a narrow SQL prefix prefilter. Punctuation
        # such as `St. Valentin`, official-vs-source `Sankt` spelling, and a small set of
        # Statistics-Austria-backed locality/postal exceptions therefore use one in-memory
        # scan of the small Austrian postal table. Matching never becomes fuzzy.
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
            resolved[
                f"{label} -> {resolution.canonical_locality} [{resolution.method}]"
            ] += 1

        session.commit()

        print(
            "jobs_at_source_repair="
            f"considered:{source_repair.considered} "
            f"repaired:{source_repair.repaired} "
            f"unresolved:{source_repair.unresolved} "
            f"failed:{source_repair.failed}"
        )
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
