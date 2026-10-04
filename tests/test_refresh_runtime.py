from pathlib import Path

from app.refresh_runtime import (
    DEFAULT_IMMOWELT_SOLVER_URL,
    REFRESH_LOCK_PATH,
    prepare_refresh_environment,
)


def test_refresh_lock_is_persistent_and_shared_with_systemd_unit() -> None:
    assert REFRESH_LOCK_PATH == Path("/var/lib/wohnwerk/refresh-runtime/refresh.lock")

    unit = (
        Path(__file__).resolve().parents[1] / "deploy" / "wohnwerk-refresh.service"
    ).read_text(encoding="utf-8")
    assert f"--lock-path {REFRESH_LOCK_PATH}" in unit


def test_prepare_refresh_environment_builds_manual_browser_runtime(tmp_path) -> None:
    root = tmp_path / "refresh-runtime"
    env = prepare_refresh_environment(
        {
            "PATH": "/usr/bin",
            "WOHNWERK_IMMOWELT_SOLVER_URL": "http://127.0.0.1:9999",
        },
        runtime_root=root,
    )

    assert env["PATH"] == "/usr/bin"
    assert env["DISPLAY"] == ":97"
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == "/var/cache/wohnwerk-playwright"
    assert env["HOME"] == str(root / "home")
    assert env["XDG_CONFIG_HOME"] == str(root / "config")
    assert env["XDG_CACHE_HOME"] == str(root / "cache")
    assert env["XDG_RUNTIME_DIR"] == str(root / "runtime")
    assert env["WOHNWERK_IMMOWELT_SOLVER_URL"] == "http://127.0.0.1:9999"
    assert DEFAULT_IMMOWELT_SOLVER_URL == "http://127.0.0.1:8877"

    for name in ("home", "config", "cache", "runtime"):
        assert (root / name).is_dir()
