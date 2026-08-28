from __future__ import annotations

import argparse
from decimal import Decimal

from app.database import SessionLocal
from app.matching import geo_coverage, load_spatial_candidate_matches


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only candidate/job/property spatial audit. Distances are PostGIS geography "
            "straight-line distances between approximate resolved points; no rows are written."
        )
    )
    parser.add_argument("--radius-km", type=float, default=50.0)
    parser.add_argument("--jobs", type=int, default=10)
    parser.add_argument("--properties-per-job", type=int, default=5)
    return parser.parse_args()


def _decimal_label(value: Decimal | None, suffix: str) -> str:
    if value is None:
        return "-"
    return f"{float(value):.0f}{suffix}"


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        coverage = geo_coverage(session)
        matches = load_spatial_candidate_matches(
            session,
            radius_km=args.radius_km,
            job_limit=args.jobs,
            properties_per_job=args.properties_per_job,
        )

        print("distance_semantics=geography_straight_line_centroid_approximation")
        print("property_location_semantics=resolved_PLZ_BEV_centroid")
        print("job_location_semantics=resolved_PLZ_or_conservative_locality_centroid")
        print(f"radius_km={args.radius_km:.1f}")
        print(f"active_properties={coverage.active_properties}")
        print(f"located_properties={coverage.located_properties}")
        print(f"property_location_ratio={coverage.property_location_ratio:.3f}")
        print(f"relevant_jobs={coverage.relevant_jobs}")
        print(f"relevant_job_locations={coverage.relevant_job_locations}")
        print(f"located_job_locations={coverage.located_job_locations}")
        print(f"jobs_with_located_location={coverage.jobs_with_located_location}")
        print(f"job_location_ratio={coverage.job_location_ratio:.3f}")
        print("mode=read-only no database changes")

        print("matched_jobs:")
        for group in matches:
            fit = group.fit
            print(
                f"  job={fit.job.id} fit={fit.result.score} "
                f"coverage={fit.result.preference_coverage:.3f} "
                f"company={fit.job.company or '-'} title={fit.job.title}"
            )
            print(f"    job_locations={'; '.join(fit.locations) or '-'}")
            if not group.properties:
                print(f"    properties=none within {args.radius_km:.1f} km")
                continue
            for item in group.properties:
                print(
                    f"    property={item.property_id} distance_km={item.distance_km:.2f} "
                    f"job_location={item.job_location_label} "
                    f"property_location={item.property_location_label} "
                    f"price={_decimal_label(item.price_eur, ' EUR')} "
                    f"living={_decimal_label(item.living_area_m2, ' m2')} "
                    f"plot={_decimal_label(item.plot_area_m2, ' m2')}"
                )
                print(f"      title={item.title}")


if __name__ == "__main__":
    main()
