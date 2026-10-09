"""Prepare a Germany-only OSRM MLD road graph in an INACTIVE staging directory.

Never downloads files, touches /var/lib/osrm active graphs, edits systemd, or
enables `WOHNWERK_ROUTING_GRAPH_COUNTRIES`. Dry-run by default. A privileged,
separately authorized operator must validate the staged graph and activate it.

Example:
  python -m scripts.stage_osrm_germany --pbf /srv/import/germany-latest.osm.pbf \
      --profile /usr/local/share/osrm/profiles/car.lua \
      --stage-dir /srv/osrm-stage/germany-20261009

Add --execute only after checking disk, RAM, input provenance, and output path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StagedGraphPlan:
    pbf: Path
    car_profile: Path
    directory: Path

    @property
    def prefix(self) -> Path:
        return self.directory / "germany-latest.osrm"

    def commands(self) -> tuple[tuple[str, ...], ...]:
        input_file = self.directory / "germany-latest.osm.pbf"
        return (
            ("osrm-extract", "-p", str(self.car_profile), str(input_file)),
            ("osrm-partition", str(self.prefix)),
            ("osrm-customize", str(self.prefix)),
        )


def plan_staging(
    *,
    pbf: Path,
    car_profile: Path,
    directory: Path,
) -> StagedGraphPlan:
    pbf = pbf.expanduser().resolve(strict=True)
    car_profile = car_profile.expanduser().resolve(strict=True)
    directory = directory.expanduser().resolve(strict=False)
    if pbf.name != "germany-latest.osm.pbf":
        raise ValueError("Require explicitly identified germany-latest.osm.pbf")
    if not pbf.is_file() or not car_profile.is_file():
        raise ValueError("PBF and car.lua must be existing regular files")
    if car_profile.suffix != ".lua":
        raise ValueError("OSRM routing profile must be a .lua file")
    if pbf == car_profile or directory.exists():
        raise ValueError("Staging directory must not already exist")
    if directory == Path("/") or directory == Path("/var/lib/osrm"):
        raise ValueError("Never stage into the active routing directory")
    if Path("/var/lib/osrm") in directory.parents:
        raise ValueError("Never create staging files under the active routing directory")
    if directory in pbf.parents or directory in car_profile.parents:
        raise ValueError("Input files may not live inside the staging directory")
    if any(item == ".." for item in directory.parts):
        raise ValueError("Unsafe staging directory traversal")
    return StagedGraphPlan(pbf=pbf, car_profile=car_profile, directory=directory)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def execute_staging(
    plan: StagedGraphPlan,
    *,
    runner=subprocess.run,
) -> dict[str, str]:
    """Build a graph without ever replacing or reloading the active service."""
    for binary in ("osrm-extract", "osrm-partition", "osrm-customize"):
        if shutil.which(binary) is None:
            raise RuntimeError(f"OSRM build tool is missing: {binary}")
    # Directory creation is exclusive; no existing graph is ever overwritten.
    plan.directory.mkdir(parents=False, exist_ok=False)
    source_link = plan.directory / "germany-latest.osm.pbf"
    source_link.symlink_to(plan.pbf)
    for command in plan.commands():
        runner(list(command), check=True)
    if not plan.prefix.is_file() or plan.prefix.stat().st_size == 0:
        raise RuntimeError("Expected nonempty germany-latest.osrm was not generated")
    for suffix in (".partition", ".cells"):
        output = Path(str(plan.prefix) + suffix)
        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError(f"Missing MLD graph artifact: {output.name}")
    manifest = {
        "state": "staged_not_activated",
        "country": "DE",
        "algorithm": "MLD",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "pbf_sha256": _sha256(plan.pbf),
        "car_profile_sha256": _sha256(plan.car_profile),
        "graph_prefix": str(plan.prefix),
    }
    manifest_path = plan.directory / "wohnwerk-stage-manifest.json"
    # A manifest records provenance but proves neither complete national
    # coverage nor correct road distances. The independent live OSRM probe
    # and explicit operator activation are still mandatory.
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument(
        "--execute", action="store_true", help="Build an INACTIVE graph; no service cutover"
    )
    args = parser.parse_args()
    try:
        plan = plan_staging(
            pbf=args.pbf, car_profile=args.profile, directory=args.stage_dir
        )
        print(f"Source PBF: {plan.pbf}", flush=True)
        print(f"Car profile: {plan.car_profile}", flush=True)
        print(f"Inactive output: {plan.directory}", flush=True)
        for command in plan.commands():
            print("Planned argument vector:", json.dumps(command), flush=True)
        if not args.execute:
            print("DRY RUN ONLY: no files, service, or routing flags changed.")
            return 0
        manifest = execute_staging(plan)
        print(f"STAGED (NOT ACTIVATED): {manifest['graph_prefix']}")
        print("Operator must independently validate Germany road routing before cutover.")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"STAGING FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
