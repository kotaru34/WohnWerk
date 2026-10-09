"""Verify and unpack a WohnWerk Germany OSRM ZIP into an INACTIVE stage directory.

Dry-run by default. Never edits systemd, never writes /var/lib/osrm, never enables
routing flags. Intended for a separately authorized Sentinel transfer/install step.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

MANIFEST_NAME = "wohnwerk-osrm-germany-manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _safe_members(archive: zipfile.ZipFile) -> list[str]:
    names = archive.namelist()
    if not names or len(names) != len(set(names)):
        raise ValueError("archive member list is empty or contains duplicates")
    for name in names:
        path = Path(name)
        if (
            path.is_absolute()
            or len(path.parts) != 1
            or name.startswith(("/", "\\"))
            or ".." in path.parts
        ):
            raise ValueError(f"unsafe archive member: {name!r}")
    return names


def inspect_package(archive_path: Path) -> tuple[dict, list[str]]:
    archive_path = archive_path.expanduser().resolve(strict=True)
    if not archive_path.is_file() or archive_path.suffix.casefold() != ".zip":
        raise ValueError("expected an existing ZIP package")
    with zipfile.ZipFile(archive_path) as archive:
        names = _safe_members(archive)
        if MANIFEST_NAME not in names:
            raise ValueError("package manifest is missing")
        manifest = json.loads(archive.read(MANIFEST_NAME))
    if manifest.get("schema") != "wohnwerk-osrm-germany-package-v1":
        raise ValueError("unexpected package manifest schema")
    if manifest.get("state") != "built_and_locally_accepted_not_deployed":
        raise ValueError("graph was not locally accepted")
    if manifest.get("country") != "DE" or manifest.get("algorithm") != "MLD":
        raise ValueError("package is not a German MLD graph")
    if not (manifest.get("acceptance") or {}).get("all_passed"):
        raise ValueError("package route acceptance did not pass")
    required = [str(value) for value in manifest.get("required_inputs") or []]
    if not required or any(value not in names for value in required):
        raise ValueError("package is missing required osrm-routed input files")
    artifact_names = {
        str(row.get("name"))
        for row in manifest.get("artifacts") or []
        if isinstance(row, dict) and row.get("name")
    }
    if not set(required).issubset(artifact_names):
        raise ValueError("required inputs are not covered by artifact provenance")
    return manifest, names


def stage_package(archive_path: Path, stage_dir: Path) -> dict[str, object]:
    archive_path = archive_path.expanduser().resolve(strict=True)
    stage_dir = stage_dir.expanduser().resolve(strict=False)
    if stage_dir.exists():
        raise ValueError("inactive stage directory must not already exist")
    if stage_dir == Path("/") or Path("/var/lib/osrm") in (stage_dir, *stage_dir.parents):
        raise ValueError("never unpack transfer package into active OSRM storage")

    manifest, names = inspect_package(archive_path)
    stage_dir.mkdir(parents=False, exist_ok=False)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for name in names:
                if name == "germany-latest.osm.pbf":
                    continue
                with archive.open(name) as src, (stage_dir / name).open("xb") as dst:
                    shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)

        expected = {
            str(row["name"]): str(row["sha256"])
            for row in manifest.get("artifacts") or []
            if isinstance(row, dict) and row.get("name") and row.get("sha256")
        }
        for name, digest in expected.items():
            path = stage_dir / name
            if not path.is_file() or _sha256(path) != digest:
                raise RuntimeError(f"staged artifact checksum mismatch: {name}")

        required = [str(value) for value in manifest["required_inputs"]]
        missing = [name for name in required if not (stage_dir / name).is_file()]
        if missing:
            raise RuntimeError(f"required routed artifacts missing after extraction: {missing}")

        staged_manifest = dict(manifest)
        staged_manifest["state"] = "staged_not_activated"
        staged_manifest["transfer_archive_sha256"] = _sha256(archive_path)
        (stage_dir / MANIFEST_NAME).write_text(
            json.dumps(staged_manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return {
            "state": "staged_not_activated",
            "stage_dir": str(stage_dir),
            "archive_sha256": staged_manifest["transfer_archive_sha256"],
            "required_files": len(required),
            "artifact_files": len(expected),
        }
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        manifest, names = inspect_package(args.archive)
        print(json.dumps({
            "country": manifest["country"],
            "algorithm": manifest["algorithm"],
            "accepted": manifest["acceptance"]["all_passed"],
            "members": len(names),
            "target": str(args.stage_dir),
            "mode": "execute" if args.execute else "dry_run",
        }, ensure_ascii=False))
        if not args.execute:
            return 0
        print(json.dumps(stage_package(args.archive, args.stage_dir), ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"STAGING FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
