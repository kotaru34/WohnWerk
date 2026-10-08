"""Read-only Germany OSRM acceptance probe; never starts services or enables routing.

Run from the authorized host after the Germany MLD road graph has been built
and loaded. A clean result is necessary, but not sufficient, for graph cutover.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from app.routing import OSRMClient, RouteEstimate, RoutingError, RoutingPoint


@dataclass(frozen=True)
class City:
    name: str
    point: RoutingPoint


CITIES = {
    "munich": City("München", RoutingPoint(11.5755, 48.1374)),
    "berlin": City("Berlin", RoutingPoint(13.4050, 52.5200)),
    "hamburg": City("Hamburg", RoutingPoint(9.9921, 53.5503)),
    "cologne": City("Köln", RoutingPoint(6.9583, 50.9413)),
    "dresden": City("Dresden", RoutingPoint(13.7373, 51.0504)),
}

# Intentionally permissive road-distance sanity bands, not exact route claims.
# Snap distance and geodesic plausibility are additionally checked by OSRMClient.
CHECKS = (
    ("munich", "berlin", 380, 850),
    ("munich", "hamburg", 550, 1100),
    ("munich", "cologne", 380, 900),
    ("hamburg", "berlin", 200, 450),
    ("hamburg", "dresden", 330, 800),
)


def assess_routes(router: OSRMClient) -> list[str]:
    failures: list[str] = []
    for origin in ("munich", "hamburg"):
        cases = [check for check in CHECKS if check[0] == origin]
        city = CITIES[origin]
        destinations = [CITIES[destination].point for _, destination, _, _ in cases]
        try:
            estimates = router.table(city.point, destinations)
        except (RoutingError, ValueError) as exc:
            failures.append(f"{city.name}: routing failed: {exc}")
            continue
        if len(estimates) != len(cases):
            failures.append(f"{city.name}: table returned an unexpected row count")
            continue
        for (_origin, target, low, high), result in zip(cases, estimates, strict=True):
            if not isinstance(result, RouteEstimate) or not result.reachable:
                failures.append(f"{city.name} → {CITIES[target].name}: unavailable")
                continue
            assert result.distance_km is not None
            assert result.duration_minutes is not None
            if not low <= result.distance_km <= high:
                failures.append(
                    f"{city.name} → {CITIES[target].name}: "
                    f"{result.distance_km:.1f} km outside {low}–{high} km"
                )
            elif result.duration_minutes <= 0:
                failures.append(f"{city.name} → {CITIES[target].name}: invalid drive time")
            else:
                print(
                    f"OK {city.name} → {CITIES[target].name}: "
                    f"{result.distance_km:.1f} km, {result.duration_minutes:.0f} min"
                )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--max-snap-metres", type=float, default=1000.0)
    args = parser.parse_args()
    with OSRMClient(
        args.base_url, timeout_seconds=12, max_snap_distance_metres=args.max_snap_metres
    ) as router:
        failures = assess_routes(router)
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        print("Graph is NOT accepted. Do not enable WOHNWERK_ROUTING_GRAPH_COUNTRIES.")
        return 1
    print("Germany route probes passed. Complete independent checks before enabling DE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
