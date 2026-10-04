from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

REFRESH_RUNTIME_ROOT = Path("/var/lib/wohnwerk/refresh-runtime")
REFRESH_LOCK_PATH = REFRESH_RUNTIME_ROOT / "refresh.lock"
DEFAULT_IMMOWELT_SOLVER_URL = "http://127.0.0.1:8877"


def prepare_refresh_environment(
    base_env: Mapping[str, str] | None = None,
    *,
    runtime_root: Path | None = None,
) -> dict[str, str]:
    """Build the browser/runtime environment for manual refresh subprocesses.

    Automatic refreshes receive equivalent values from systemd. Admin-launched
    refreshes are children of the web service instead, so they need a writable runtime
    outside systemd's short-lived RuntimeDirectory plus the headed-browser settings.
    """
    root = runtime_root or REFRESH_RUNTIME_ROOT
    home = root / "home"
    config = root / "config"
    cache = root / "cache"
    runtime = root / "runtime"

    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in (home, config, cache, runtime):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)

    env = dict(os.environ if base_env is None else base_env)
    defaults = {
        "DISPLAY": ":97",
        "PLAYWRIGHT_BROWSERS_PATH": "/var/cache/wohnwerk-playwright",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(config),
        "XDG_CACHE_HOME": str(cache),
        "XDG_RUNTIME_DIR": str(runtime),
        "WOHNWERK_IMMOWELT_SOLVER_URL": DEFAULT_IMMOWELT_SOLVER_URL,
    }
    for key, value in defaults.items():
        env.setdefault(key, value)
    return env
