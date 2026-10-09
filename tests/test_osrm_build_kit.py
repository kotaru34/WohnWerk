from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _verify_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "osrm_germany_build_kit"
        / "verify.py"
    )
    spec = spec_from_file_location("wohnwerk_osrm_verify_test", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_kit_accepts_large_legitimate_road_vs_air_difference() -> None:
    verify = _verify_module()
    probe = verify.Probe(
        "user-shape",
        verify.MUNICH,
        verify.BERLIN,
        450,
        750,
    )
    result = verify.validate(probe, {
        "distance_km": 600.0,
        "duration_minutes": 360.0,
        "source_snap_m": 25.0,
        "destination_snap_m": 30.0,
    })
    assert result["ok"] is True
    assert result["distance_km"] == 600.0


def test_build_kit_rejects_distant_snap_and_impossible_effective_speed() -> None:
    verify = _verify_module()
    probe = verify.Probe("bad", verify.MUNICH, verify.BERLIN, 450, 750)
    result = verify.validate(probe, {
        "distance_km": 600.0,
        "duration_minutes": 60.0,
        "source_snap_m": 15.0,
        "destination_snap_m": 5000.0,
    })
    assert result["ok"] is False
    assert any("destination snap" in error for error in result["errors"])
    assert any("implausibly high" in error for error in result["errors"])


def test_build_kit_has_five_separated_german_intercity_probes() -> None:
    verify = _verify_module()
    assert len(verify.PROBES) == 5
    names = {item.name for item in verify.PROBES}
    assert "München → Berlin" in names
    assert "Hamburg → Dresden" in names
