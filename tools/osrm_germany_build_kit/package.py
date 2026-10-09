#!/usr/bin/env python3
"""Package a locally accepted Germany OSRM graph into a transferable ZIP64 archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

GRAPH_PREFIX = "germany-latest.osrm"
MANIFEST = "wohnwerk-osrm-germany-manifest.json"
ACCEPTANCE = "wohnwerk-osrm-acceptance.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    work = args.work_dir.expanduser().resolve()
    manifest_path = work / MANIFEST
    if not manifest_path.is_file():
        raise SystemExit(f"missing {MANIFEST}; run build.py successfully first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("state") != "built_and_locally_accepted_not_deployed":
        raise SystemExit("manifest is not a locally accepted Germany build")
    if not (manifest.get("acceptance") or {}).get("all_passed"):
        raise SystemExit("acceptance did not pass; refusing to package")

    required = [str(item) for item in manifest.get("required_inputs") or []]
    if not required:
        raise SystemExit("manifest has no osrm-routed required input list")
    missing = [name for name in required if not (work / name).is_file()]
    if missing:
        raise SystemExit(f"required graph files are missing: {missing}")

    artifact_names = sorted({
        path.name for path in work.glob(f"{GRAPH_PREFIX}*") if path.is_file()
    })
    if not artifact_names:
        raise SystemExit("no graph artifacts found")

    output = args.output
    if output is None:
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        output = work / f"wohnwerk-osrm-germany-{stamp}.zip"
    output = output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing {output}")

    include = [MANIFEST]
    if (work / ACCEPTANCE).is_file():
        include.append(ACCEPTANCE)
    include.extend(artifact_names)

    # ZIP64 works in Python/MSYS2/Windows without extra tar/zstd dependencies.
    # OSRM graph files are already compact; store mode avoids wasting hours of CPU
    # for marginal compression while preserving exact bytes/checksums.
    with zipfile.ZipFile(
        output,
        mode="x",
        compression=zipfile.ZIP_STORED,
        allowZip64=True,
    ) as archive:
        for name in include:
            path = work / name
            archive.write(path, arcname=name)

    package_sha = sha256(output)
    checksum = output.with_suffix(output.suffix + ".sha256")
    checksum.write_text(f"{package_sha}  {output.name}\n", encoding="ascii")
    package_manifest = {
        "schema": "wohnwerk-osrm-transfer-package-v1",
        "package": output.name,
        "package_sha256": package_sha,
        "bytes": output.stat().st_size,
        "files": include,
        "required_inputs": required,
    }
    output.with_suffix(output.suffix + ".json").write_text(
        json.dumps(package_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(output)
    print(checksum)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
