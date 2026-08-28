from __future__ import annotations

import argparse
from decimal import Decimal
from time import perf_counter

from app.config import get_settings
from app.database import SessionLocal
from app.matching import geo_coverage
from app.road_matching import load_road_candidate_matches
from app.routing import OSRMClient, RoutingError


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description=(
            "Read-only candidate/job/property road-routing audit. PostGIS Luftlinie "
            "prefilters candidates; local OSRM refines them by fastest driving route."
        )
    )
    parser.add_argument("--radius-km", type=float, default=50.0)
    parser.add_argument("--jobs", type=int, default=10)
    parser.add_argument("--properties-per-job", type=int, default=5)
    parser.add_argument(
        "--prefilter-properties-per-job",
        type=int,
        default=settings.routing_prefilter_properties_per_job,
    )
    parser.add_argument("--osrm-url", default=settings.routing_base_url)
    parser.add_argument("--timeout", type=float, default=settings.routing_timeout_seconds)
    parser.add_argument(
        "--max-table-coordinates",
        type=int,
        default=settings.routing_max_table_coordinates,
    )
    return parser.parse_args()


def _decimal_label(value: Decimal | None, suffix: str) -> str:
    if value is None:
        return "-"
    return f"{float(value):.0f}{suffix}"


def _detour_label(road_km: float | None, air_km: float) -> str:
    if road_km is None or air_km <= 0:
        return "-"
    return f"{road_km / air_km:.2f}"


def main() -> None:
    args = parse_args()

    with SessionLocal() as session:
        coverage = geo_coverage(session)
        started = perf_counter()
        try:
            with OSRMClient(
                args.osrm_url,
                timeout_seconds=args.timeout,
                max_table_coordinates=args.max_table_coordinates,
            ) as router:
                matches = load_road_candidate_matches(
                    session,
                    router,
                    radius_km=args.radius_km,
                    job_limit=args.jobs,
                    properties_per_job=args.properties_per_job,
                    prefilter_properties_per_job=args.prefilter_properties_per_job,
                )
        except RoutingError as exc:
            print("routing_status=failed")
            print(f"routing_error={exc}")
            raise SystemExit(2) from exc
        routing_seconds = perf_counter() - started

        print("routing_status=ok")
        print("distance_semantics=fastest_driving_route_over_OSM_centroid_approximation")
        print("duration_semantics=fastest_driving_route_estimate")
        print("prefilter_semantics=PostGIS_geography_Luftlinie")
        print("property_location_semantics=resolved_PLZ_BEV_centroid")
        print("job_location_semantics=resolved_PLZ_or_conservative_locality_centroid")
        print(f"radius_km={args.radius_km:.1f}")
        print(f"prefilter_properties_per_job={args.prefilter_properties_per_job}")
        print(f"routing_seconds={routing_seconds:.3f}")
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
            fit = group.spatial.fit
            print(
                f"  job={fit.job.id} fit={fit.result.score} "
                f"coverage={fit.result.preference_coverage:.3f} "
                f"company={fit.job.company or '-'} title={fit.job.title}"
            )
            print(f"    job_locations={'; '.join(fit.locations) or '-'}")
            if not group.properties:
                print(f"    properties=none within {args.radius_km:.1f} km by road")
                continue

            for item in group.properties:
                spatial = item.spatial
                print(
                    f"    property={spatial.property_id} "
                    f"road_km={item.road_distance_km:.2f} "
                    f"drive_min={item.road_duration_minutes:.1f} "
                    f"luftlinie_km={spatial.distance_km:.2f} "
                    f"detour_factor={_detour_label(item.road_distance_km, spatial.distance_km)} "
                    f"job_location={item.road_job_location_label or '-'} "
                    f"property_location={spatial.property_location_label} "
                    f"price={_decimal_label(spatial.price_eur, ' EUR')} "
                    f"living={_decimal_label(spatial.living_area_m2, ' m2')} "
                    f"plot={_decimal_label(spatial.plot_area_m2, ' m2')}"
                )
                print(f"      title={spatial.title}")


if __name__ == "__main__":
    main()
