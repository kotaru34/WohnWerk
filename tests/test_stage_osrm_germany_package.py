import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.stage_osrm_germany_package import inspect_package, stage_package


def _package(tmp_path: Path, *, accepted: bool = True) -> Path:
    files = {
        "germany-latest.osrm.cells": b"cells",
        "germany-latest.osrm.partition": b"partition",
        "germany-latest.osrm.ebg": b"ebg",
    }
    manifest = {
        "schema": "wohnwerk-osrm-germany-package-v1",
        "state": "built_and_locally_accepted_not_deployed",
        "country": "DE",
        "algorithm": "MLD",
        "acceptance": {"all_passed": accepted},
        "required_inputs": list(files),
        "artifacts": [
            {
                "name": name,
                "bytes": len(value),
                "sha256": hashlib.sha256(value).hexdigest(),
            }
            for name, value in files.items()
        ],
    }
    path = tmp_path / "germany.zip"
    with zipfile.ZipFile(path, "w", allowZip64=True) as archive:
        archive.writestr(
            "wohnwerk-osrm-germany-manifest.json",
            json.dumps(manifest),
        )
        for name, value in files.items():
            archive.writestr(name, value)
    return path


def test_stage_package_verifies_manifest_and_artifact_checksums(tmp_path: Path) -> None:
    archive = _package(tmp_path)
    stage = tmp_path / "inactive-germany"
    result = stage_package(archive, stage)
    assert result["state"] == "staged_not_activated"
    assert (stage / "germany-latest.osrm.cells").read_bytes() == b"cells"
    written = json.loads(
        (stage / "wohnwerk-osrm-germany-manifest.json").read_text(encoding="utf-8")
    )
    assert written["state"] == "staged_not_activated"
    assert len(written["transfer_archive_sha256"]) == 64


def test_stage_package_rejects_unaccepted_or_path_traversal_zip(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="acceptance"):
        inspect_package(_package(tmp_path, accepted=False))

    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../escape", b"no")
        archive.writestr(
            "wohnwerk-osrm-germany-manifest.json",
            json.dumps({
                "schema": "wohnwerk-osrm-germany-package-v1",
                "state": "built_and_locally_accepted_not_deployed",
                "country": "DE",
                "algorithm": "MLD",
                "acceptance": {"all_passed": True},
                "required_inputs": ["../escape"],
                "artifacts": [{
                    "name": "../escape",
                    "sha256": hashlib.sha256(b"no").hexdigest(),
                }],
            }),
        )
    with pytest.raises(ValueError, match="unsafe archive member"):
        inspect_package(unsafe)


def test_stage_package_refuses_existing_or_active_target(tmp_path: Path) -> None:
    archive = _package(tmp_path)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="must not already exist"):
        stage_package(archive, existing)
    with pytest.raises(ValueError, match="active OSRM"):
        stage_package(archive, Path("/var/lib/osrm/stage"))
