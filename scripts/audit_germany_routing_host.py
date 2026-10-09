"""Read-only, credential-free German OSRM production cutover readiness audit.

This does not install software, alter services, inspect .env, open the private
database, activate routing, or declare geography independently verified.
It reports blocking operator tasks before a separately authorized deployment.

Usage: python -m scripts.audit_germany_routing_host
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

GERMANY_GRAPH = Path("/var/lib/osrm/germany-latest.osrm")
EXPECTED_UNIT = "wohnwerk-osrm.service"
_ALLOWED_BINARY_NAMES = (
    "osrm-extract",
    "osrm-partition",
    "osrm-customize",
    "osrm-routed",
)
_ROUTED_GRAPH = re.compile(r"\bosrm-routed\s+(\S+\.osrm)(?=\s|$)")


@dataclass(frozen=True, slots=True)
class RoutingHostSnapshot:
    country: str | None
    service: str | None
    health_version: str | None
    routing_mode: str | None
    osrm_graph_path: str | None
    germany_graph_files: dict[str, bool]
    osrm_commands_installed: dict[str, bool]
    available_memory_mib: int | None
    free_disk_gib: float | None


def _host_health() -> dict:
    try:
        with urlopen("http://127.0.0.1:8000/health", timeout=5) as response:
            if response.status != 200:
                return {}
            payload = json.load(response)
            return payload if isinstance(payload, dict) else {}
    except (TimeoutError, OSError, HTTPError, URLError, ValueError, json.JSONDecodeError):
        return {}


def _service_graph_path() -> str | None:
    try:
        p = subprocess.run(
            ["systemctl", "cat", EXPECTED_UNIT],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    # systemctl cat includes unit contents and possibly overrides.
    # A drop-in with its own ExecStart takes precedence, so inspect the final
    # nonempty routed command rather than assuming a single unit stanza.
    matches = _ROUTED_GRAPH.findall(p.stdout)
    return matches[-1] if matches else None


def _mem_available_mib() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except (OSError, IndexError, ValueError):
        return None
    return None


def collect_host_snapshot() -> RoutingHostSnapshot:
    health = _host_health()
    files = {
        label: Path(str(GERMANY_GRAPH) + suffix).is_file()
        for label, suffix in (
            ("base", ""),
            ("partition", ".partition"),
            ("cells", ".cells"),
        )
    }
    try:
        free_disk_gib = round(shutil.disk_usage(GERMANY_GRAPH.parent).free / 1024**3, 2)
    except OSError:
        free_disk_gib = None

    return RoutingHostSnapshot(
        country=health.get("country"),
        service=health.get("service"),
        health_version=health.get("version"),
        routing_mode=health.get("road_routing_mode"),
        osrm_graph_path=_service_graph_path(),
        germany_graph_files=files,
        osrm_commands_installed={
            binary: shutil.which(binary) is not None for binary in _ALLOWED_BINARY_NAMES
        },
        available_memory_mib=_mem_available_mib(),
        free_disk_gib=free_disk_gib,
    )


def assess_readiness(snapshot: RoutingHostSnapshot) -> list[str]:
    blockers = []
    if snapshot.service != "wohnwerk":
        blockers.append("wohnwerk_health_unavailable")
    if snapshot.country != "DE":
        blockers.append("active_application_country_not_DE")
    if snapshot.osrm_graph_path != str(GERMANY_GRAPH):
        blockers.append("osrm_service_uses_non_german_graph")
    if not all(snapshot.germany_graph_files.values()):
        blockers.append("germany_mld_graph_artifacts_missing")
    if not snapshot.osrm_commands_installed.get("osrm-routed", False):
        blockers.append("osrm_runtime_missing")
    if snapshot.routing_mode != "de_graph_declared":
        blockers.append("de_routing_not_declared_after_acceptance")
    # OSRM preprocessors are not mandatory for *using* an independently
    # staged verified graph, but their absence prevents on-host build.
    return blockers


def main() -> int:
    snapshot = collect_host_snapshot()
    blockers = assess_readiness(snapshot)
    print(json.dumps({
        "status": "blocked" if blockers else "config_checks_passed_live_validation_required",
        "blockers": blockers,
        "runtime": {
            "country": snapshot.country,
            "health_version": snapshot.health_version,
            "routing_mode": snapshot.routing_mode,
            "osrm_graph_path": snapshot.osrm_graph_path,
            "germany_graph_files": snapshot.germany_graph_files,
            "osrm_commands_installed": snapshot.osrm_commands_installed,
            "available_memory_mib": snapshot.available_memory_mib,
            "free_disk_gib": snapshot.free_disk_gib,
        },
        "operator_notice": (
            "Read-only status, NOT route acceptance, sudo authorization, "
            "or permission for service cutover"
        ),
    }, ensure_ascii=False, sort_keys=True))
    return 1 if blockers else 0


if __name__ == "__main__":
    sys.exit(main())
