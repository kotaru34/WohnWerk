from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "production_maintenance_v0428.sh"


def test_production_maintenance_script_is_valid_bash() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_production_maintenance_does_not_repeat_077_or_unconditional_revocation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "umask 022" in source
    assert "umask 077" not in source
    assert 'case "$1" in recover|deploy)' in source
    assert "repair_modes \"$BASE\"" in source
    assert "repair_modes \"$TARGET\"" in source
    assert "ROLLBACK UNHEALTHY" in source
    assert "DEPLOY SUCCESS" in source
    assert "31451e873310cda471833bed36fbc3f6718fa35f" in source
    assert "83632033dbb4c4017ad8a3aba170bc94d63f8ba8" in source
    assert "NOPASSWD: ALL" not in source
