#!/usr/bin/env python3
"""Strict read-only acceptance of a Germany OSRM Table endpoint."""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Point:
    lon: float
    lat: float


@dataclass(frozen=True)
class Probe:
    name: str
    origin: Point
    destination: Point
    min_km: float
    max_km: float


MUNICH = Point(11.5755, 48.1374)
BERLIN = Point(13.4050, 52.5200)
HAMBURG = Point(9.9921, 53.5503)
COLOGNE = Point(6.9583, 50.9413)
DRESDEN = Point(13.7373, 51.0504)

PROBES = (
    Probe("München → Berlin", MUNICH, BERLIN, 450, 750),
    Probe("München → Hamburg", MUNICH, HAMBURG, 650, 950),
    Probe("München → Köln", MUNICH, COLOGNE, 500, 800),
    Probe("Hamburg → Berlin", HAMBURG, BERLIN, 230, 380),
    Probe("Hamburg → Dresden", HAMBURG, DRESDEN, 420, 650),
)
MAX_SNAP_METRES = 1000.0
MAX_EFFECTIVE_SPEED_KMH = 180.0
MIN_EFFECTIVE_SPEED_KMH = 15.0


def great_circle_km(a: Point, b: Point) -> float:
    r = 6371.0088
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + (
        math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


def get_json(url: str) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": "WohnWerk-OSRM-acceptance/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {url}")
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("OSRM response is not an object")
    return payload


def table(base: str, probe: Probe) -> dict[str, float]:
    coords = (
        f"{probe.origin.lon:.6f},{probe.origin.lat:.6f};"
        f"{probe.destination.lon:.6f},{probe.destination.lat:.6f}"
    )
    params = urllib.parse.urlencode({
        "sources": "0",
        "destinations": "1",
        "annotations": "distance,duration",
    })
    payload = get_json(f"{base.rstrip('/')}/table/v1/driving/{coords}?{params}")
    if payload.get("code") != "Ok":
        raise RuntimeError(f"{probe.name}: OSRM code={payload.get('code')}")
    try:
        metres = float(payload["distances"][0][0])
        seconds = float(payload["durations"][0][0])
        source_snap = float(payload["sources"][0]["distance"])
        destination_snap = float(payload["destinations"][0]["distance"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError(f"{probe.name}: malformed Table response") from exc
    values = (metres, seconds, source_snap, destination_snap)
    if not all(math.isfinite(item) and item >= 0 for item in values):
        raise RuntimeError(f"{probe.name}: non-finite/negative route metrics")
    return {
        "distance_km": metres / 1000.0,
        "duration_minutes": seconds / 60.0,
        "source_snap_m": source_snap,
        "destination_snap_m": destination_snap,
    }


def validate(probe: Probe, route: dict[str, float]) -> dict[str, object]:
    errors: list[str] = []
    road_km = route["distance_km"]
    duration_min = route["duration_minutes"]
    direct_km = great_circle_km(probe.origin, probe.destination)
    snap_allowance_km = (
        route["source_snap_m"] + route["destination_snap_m"] + 250.0
    ) / 1000.0
    if route["source_snap_m"] > MAX_SNAP_METRES:
        errors.append(f"source snap {route['source_snap_m']:.0f} m")
    if route["destination_snap_m"] > MAX_SNAP_METRES:
        errors.append(f"destination snap {route['destination_snap_m']:.0f} m")
    if road_km + snap_allowance_km < direct_km:
        errors.append(
            f"road distance {road_km:.1f} km below geodesic lower bound {direct_km:.1f} km"
        )
    if not probe.min_km <= road_km <= probe.max_km:
        errors.append(
            f"road distance {road_km:.1f} outside {probe.min_km:.0f}–{probe.max_km:.0f} km"
        )
    if duration_min <= 0:
        errors.append("duration is not positive")
        speed = math.inf
    else:
        speed = road_km / (duration_min / 60.0)
        if speed > MAX_EFFECTIVE_SPEED_KMH:
            errors.append(f"effective speed {speed:.1f} km/h implausibly high")
        if speed < MIN_EFFECTIVE_SPEED_KMH:
            errors.append(f"effective speed {speed:.1f} km/h implausibly low")
    return {
        "name": probe.name,
        "direct_km": round(direct_km, 2),
        **{key: round(value, 2) for key, value in route.items()},
        "effective_speed_kmh": round(speed, 2) if math.isfinite(speed) else None,
        "ok": not errors,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    results: list[dict[str, object]] = []
    for probe in PROBES:
        try:
            result = validate(probe, table(args.base_url, probe))
        except Exception as exc:
            result = {
                "name": probe.name,
                "ok": False,
                "errors": [f"{type(exc).__name__}: {exc}"],
            }
        results.append(result)
        state = "OK" if result["ok"] else "FAIL"
        print(
            f"{state} {probe.name}: "
            f"{result.get('distance_km', '?')} km, "
            f"{result.get('duration_minutes', '?')} min, "
            f"snaps={result.get('source_snap_m', '?')}/{result.get('destination_snap_m', '?')} m"
        )
        for error in result.get("errors", []):
            print(f"  - {error}")

    report = {
        "schema": "wohnwerk-osrm-germany-acceptance-v1",
        "base_url": args.base_url,
        "max_snap_metres": MAX_SNAP_METRES,
        "all_passed": all(bool(row["ok"]) for row in results),
        "probes": results,
    }
    if args.json_out:
        args.json_out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
