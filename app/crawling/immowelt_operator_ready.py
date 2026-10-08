from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.refresh import MANUAL_RUN_REQUEST_ENV

DEFAULT_READY_ROOT = Path("/var/lib/wohnwerk/challenge-state/immowelt-de")
OPERATOR_READY_TTL = timedelta(minutes=15)

def requires_manual_immowelt_operator(paused: Any) -> bool:
    """Avoid scheduled revalidation of a paused interactive CAPTCHA."""
    if paused is None or str(paused.status) != "paused":
        return False
    active = (paused.run_metadata or {}).get("active_challenge")
    if not isinstance(active, dict):
        return False
    challenge = active.get("challenge")
    if not isinstance(challenge, dict):
        return False
    return str(challenge.get("datadome_challenge_type") or "").casefold() in {"fe", "bv"}



def ready_path(root: Path = DEFAULT_READY_ROOT) -> Path:
    return root / "operator-ready.json"


@contextmanager
def _ready_lock(root: Path) -> Iterator[None]:
    # The web and refresh worker are separate processes; locking a persistent
    # file closes the bind/consume/cancel race without locking the data inode.
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(root / "operator-ready.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read(root: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(ready_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_operator_readiness(
    root: Path = DEFAULT_READY_ROOT, *, now: datetime | None = None
) -> dict[str, Any]:
    """Public, token-free state for the authenticated admin interface."""
    data = _read(root)
    if data is None or data.get("version") != 1:
        return {"state": "idle"}
    expires_at = data.get("expires_at")
    try:
        deadline = datetime.fromisoformat(str(expires_at))
        if deadline.tzinfo is None:
            return {"state": "expired"}
        if (now or datetime.now(UTC)).astimezone(UTC) >= deadline.astimezone(UTC):
            return {"state": "expired", "expires_at": expires_at}
    except (ValueError, TypeError):
        return {"state": "invalid"}
    state = data.get("state")
    if state not in {"ready", "bound", "consumed"}:
        return {"state": "invalid"}
    result: dict[str, Any] = {"state": state, "expires_at": expires_at}
    if state == "consumed" and isinstance(data.get("run_id"), int):
        result["run_id"] = data["run_id"]
    return result


def _write(root: Path, data: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".operator-ready-", dir=str(root))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, separators=(",", ":"))
            file.write("\n")
        os.chmod(name, 0o600)
        os.replace(name, ready_path(root))
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def arm_operator_readiness(
    root: Path = DEFAULT_READY_ROOT, *, now: datetime | None = None
) -> dict[str, Any]:
    with _ready_lock(root):
        status = read_operator_readiness(root, now=now)
        if status["state"] in {"bound", "consumed"}:
            raise ValueError("Operator readiness is already attached to a manual run")
        current = (now or datetime.now(UTC)).astimezone(UTC)
        _write(root, {
            "version": 1,
            "state": "ready",
            "armed_at": current.isoformat(),
            "expires_at": (current + OPERATOR_READY_TTL).isoformat(),
        })
        return read_operator_readiness(root, now=current)


def clear_operator_readiness(root: Path = DEFAULT_READY_ROOT) -> None:
    with _ready_lock(root):
        if read_operator_readiness(root)["state"] == "consumed":
            raise ValueError("Active operator handoff must be cancelled from its own page")
        try:
            ready_path(root).unlink()
        except FileNotFoundError:
            pass


def bind_operator_readiness(
    request_id: str, root: Path = DEFAULT_READY_ROOT
) -> bool:
    """Bind a pre-arm to one explicit manual start, never a scheduled refresh."""
    if not request_id or not ready_path(root).is_file():
        return False
    with _ready_lock(root):
        if read_operator_readiness(root)["state"] != "ready":
            return False
        data = _read(root)
        if data is None:
            return False
        data["state"] = "bound"
        data["manual_request_id"] = request_id
        _write(root, data)
        return True


def consume_operator_readiness(
    run_id: int,
    root: Path = DEFAULT_READY_ROOT,
    *,
    request_id: str | None = None,
) -> bool:
    """One-shot matching handoff; unattended crawls cannot consume a pre-arm."""
    identity = request_id if request_id is not None else os.environ.get(
        MANUAL_RUN_REQUEST_ENV, ""
    )
    if not identity:
        return False
    with _ready_lock(root):
        data = _read(root)
        if (
            read_operator_readiness(root)["state"] != "bound"
            or not data
            or data.get("manual_request_id") != identity
        ):
            return False
        data["state"] = "consumed"
        data["run_id"] = int(run_id)
        # The operator receives the full interactive session TTL on challenge
        # detection, even if pre-readiness was close to expiring.
        data["expires_at"] = (datetime.now(UTC) + OPERATOR_READY_TTL).isoformat()
        data.pop("manual_request_id", None)
        _write(root, data)
        return True
