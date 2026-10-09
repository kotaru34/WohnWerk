"""No-network contracts for immutable, Germany-only OSRM graph staging."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import stage_osrm_germany


def _inputs(tmp_path: Path):
    source = tmp_path / "input"
    source.mkdir()
    pbf = source / "germany-latest.osm.pbf"
    pbf.write_bytes(b"synthetic OSM PBF placeholder")
    profile = source / "car.lua"
    profile.write_text("-- offline profile fixture\n", encoding="utf-8")
    return pbf, profile


def test_staging_defaults_to_read_only_dry_run(tmp_path, monkeypatch) -> None:
    pbf, profile = _inputs(tmp_path)
    target = tmp_path / "staged-de"
    monkeypatch.setattr("sys.argv", [
        "stage_osrm_germany",
        "--pbf", str(pbf),
        "--profile", str(profile),
        "--stage-dir", str(target),
    ])
    assert stage_osrm_germany.main() == 0
    assert not target.exists()


def test_staging_fails_closed_on_wrong_country_input(tmp_path) -> None:
    pbf, profile = _inputs(tmp_path)
    wrong = tmp_path / "austria-latest.osm.pbf"
    wrong.write_bytes(pbf.read_bytes())
    with pytest.raises(ValueError, match="germany-latest"):
        stage_osrm_germany.plan_staging(
            pbf=wrong, car_profile=profile, directory=tmp_path / "stage"
        )


def test_staging_must_not_overwrite_existing_active_or_staged_graph(tmp_path) -> None:
    pbf, profile = _inputs(tmp_path)
    with pytest.raises(ValueError, match="active routing directory"):
        stage_osrm_germany.plan_staging(
            pbf=pbf, car_profile=profile,
            directory=Path("/var/lib/osrm/germany-stage"),
        )

    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()
    (stage_dir / "preexisting.marker").write_text("sensitive", encoding="utf-8")
    with pytest.raises(ValueError, match="must not already exist"):
        stage_osrm_germany.plan_staging(
            pbf=pbf, car_profile=profile, directory=stage_dir
        )
    assert (stage_dir / "preexisting.marker").read_text() == "sensitive"


def test_builds_only_inactive_mld_graph_and_writes_provenance(tmp_path, monkeypatch) -> None:
    pbf, profile = _inputs(tmp_path)
    stage_dir = tmp_path / "prepared"
    plan = stage_osrm_germany.plan_staging(
        pbf=pbf, car_profile=profile, directory=stage_dir
    )
    calls = []
    monkeypatch.setattr(stage_osrm_germany.shutil, "which", lambda bin: f"/usr/bin/{bin}")

    def fake_run(argv, *, check, capture_output=False, text=False):
        assert check is True
        assert "systemctl" not in argv
        calls.append(argv)
        if argv[0] == "osrm-customize":
            for ext in (".partition", ".cells", ".ebg"):
                (stage_dir / ("germany-latest.osrm" + ext)).write_bytes(b"safe-mock")
        if argv[0] == "osrm-routed":
            assert capture_output is True and text is True
            return SimpleNamespace(stdout=".partition\n.cells\n.ebg\n")
        return SimpleNamespace(stdout="")

    manifest = stage_osrm_germany.execute_staging(plan, runner=fake_run)
    assert [args[0] for args in calls] == [
        "osrm-extract", "osrm-partition", "osrm-customize", "osrm-routed"
    ]
    assert (stage_dir / "germany-latest.osm.pbf").is_symlink()
    assert manifest["country"] == "DE"
    assert manifest["state"] == "staged_not_activated"
    assert manifest["pbf_sha256"] == hashlib.sha256(pbf.read_bytes()).hexdigest()
    assert manifest["car_profile_sha256"] == hashlib.sha256(
        profile.read_bytes()
    ).hexdigest()
    written = json.loads(
        (stage_dir / "wohnwerk-stage-manifest.json").read_text(encoding="utf-8")
    )
    assert written["algorithm"] == "MLD"
    with pytest.raises(FileExistsError):
        stage_osrm_germany.execute_staging(plan, runner=fake_run)


def test_missing_mld_artifact_never_generates_success_manifest(tmp_path, monkeypatch) -> None:
    pbf, profile = _inputs(tmp_path)
    stage_dir = tmp_path / "stage"
    plan = stage_osrm_germany.plan_staging(
        pbf=pbf, car_profile=profile, directory=stage_dir
    )
    monkeypatch.setattr(stage_osrm_germany.shutil, "which", lambda bin: bin)

    def fake_run(argv, *, check, capture_output=False, text=False):
        if argv[0] == "osrm-customize":
            (stage_dir / "germany-latest.osrm.partition").write_bytes(b"present")
            # cells is missing: graph must not be accepted.
        if argv[0] == "osrm-routed":
            return SimpleNamespace(stdout=".partition\n.cells\n")
        return SimpleNamespace(stdout="")

    with pytest.raises(RuntimeError, match="Missing OSRM runtime graph artifacts"):
        stage_osrm_germany.execute_staging(plan, runner=fake_run)
    assert stage_dir.exists()
    assert not (stage_dir / "wohnwerk-stage-manifest.json").exists()
