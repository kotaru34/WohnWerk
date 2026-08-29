from __future__ import annotations

from collections import Counter

from sqlalchemy import select

from app.database import SessionLocal
from app.jobs.jobs_at_location_repair import repair_unresolved_jobs_at_locations
from app.jobs.location_resolution import resolve_localities
from app.jobs.location_resolution_fallback import resolve_localities_full_scan
from app.models import JobLocation


def main() -> None:
    with SessionLocal() as session:
        source_repair = repair_unresolved_jobs_at_locations(session)

        # Remote-capable jobs can still have a real source-provided city. Preserve the
        # remote flag, but resolve that physical city just like an on-site vacancy.
        # Countrywide remote scopes without a concrete city are excluded naturally.
        locations = list(
            session.scalars(
                select(JobLocation)
                .where(
                    JobLocation.location.is_(None),
                    JobLocation.city.is_not(None),
                )
                .order_by(JobLocation.id)
            )
        )

        cities = {location.city for location in locations if location.city}
        resolutions = resolve_localities(session, cities)

        # The normal resolver deliberately uses a narrow SQL prefix prefilter. Punctuation
        # such as `St. Valentin` can be normalized away before that prefilter and therefore
        # miss an otherwise exact RTR locality. Only unresolved concrete cities fall back
        # to one in-memory scan of the small Austrian postal table; matching remains exact
        # after punctuation normalization and never becomes fuzzy.
        missing_cities = {city for city in cities if city not in resolutions}
        if missing_cities:
            resolutions.update(resolve_localities_full_scan(session, missing_cities))

        updated = 0
        unresolved: Counter[str] = Counter()
        resolved: Counter[str] = Counter()
        for location in locations:
            city = location.city or ""
            resolution = resolutions.get(city)
            if resolution is None:
                unresolved[city or "<missing>"] += 1
                continue
            location.location = resolution.as_wkt()
            updated += 1
            resolved[f"{city} -> {resolution.canonical_locality}"] += 1

        session.commit()

        print(
            "jobs_at_source_repair="
            f"considered:{source_repair.considered} "
            f"repaired:{source_repair.repaired} "
            f"unresolved:{source_repair.unresolved} "
            f"failed:{source_repair.failed}"
        )
        print(
            f"city_only_candidates={len(locations)} resolved={updated} "
            f"unresolved={len(locations) - updated}"
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
