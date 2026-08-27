from __future__ import annotations

from collections import Counter

from sqlalchemy import select

from app.database import SessionLocal
from app.jobs.location_resolution import resolve_localities
from app.models import JobLocation


def main() -> None:
    with SessionLocal() as session:
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

        print(f"city_only_candidates={len(locations)} resolved={updated} unresolved={len(locations) - updated}")
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
