from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.crawling.challenge import (
    ChallengeHandler,
    ChallengeRequest,
    ChallengeResult,
    ExternalCommandChallengeHandler,
)

IMMOWELT_HOSTS = {"immowelt.de", "www.immowelt.de"}
DATADOME_HOST_SUFFIXES = ("captcha-delivery.com", "captcha-delivery.net")
DATADOME_MARKERS = ("dd_captcha", "captcha-delivery.com", "captcha-delivery.net")
DEFAULT_SOLVER_URL = "http://127.0.0.1:8877"


class SolverBridgeError(RuntimeError):
    """Expected local-solver transport or response failure."""


def _host(raw_url: str | None) -> str:
    return (urlparse(str(raw_url or "")).hostname or "").casefold()


def _is_datadome_challenge(request: ChallengeRequest) -> bool:
    challenge = dict(request.challenge or {})
    candidate_urls = (
        challenge.get("challenge_url"),
        challenge.get("final_url"),
        request.handoff_state.get("current_url"),
    )
    for candidate in candidate_urls:
        host = _host(str(candidate or ""))
        if any(host == suffix or host.endswith("." + suffix) for suffix in DATADOME_HOST_SUFFIXES):
            return True

    markers = challenge.get("markers")
    if isinstance(markers, list):
        normalized = " ".join(str(marker).casefold() for marker in markers)
        if any(marker in normalized for marker in DATADOME_MARKERS):
            return True
    return False


def _atomic_json(path: Path, payload: dict[str, Any], *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


class ImmoweltDataDomeSolverHandler(ChallengeHandler):
    """Bridge Immowelt DataDome handoffs to the local solver without lying about success.

    The sidecar runs its own CloakBrowser session. A DataDome cookie is replayable only when
    the protected request uses the same public IP and exact User-Agent. The handler therefore
    never edits Playwright state directly. It writes a narrow browser patch beside the
    persisted handoff; the Immowelt headed adapter validates and applies that patch while
    recreating its own browser context. If the same clearance candidate is produced again for
    the same crawl run, the handler defers instead of creating a resolved/challenge loop.
    """

    def __init__(
        self,
        solver_url: str = DEFAULT_SOLVER_URL,
        *,
        timeout_seconds: float = 75.0,
        max_candidates_per_run: int = 2,
    ) -> None:
        normalized_solver_url = solver_url.rstrip("/")
        parsed_solver = urlparse(normalized_solver_url)
        if (
            parsed_solver.scheme not in {"http", "https"}
            or parsed_solver.hostname not in {"127.0.0.1", "::1", "localhost"}
            or parsed_solver.username is not None
            or parsed_solver.password is not None
            or parsed_solver.query
            or parsed_solver.fragment
            or parsed_solver.path not in {"", "/"}
        ):
            raise ValueError(
                "Immowelt DataDome solver must be an uncredentialed loopback HTTP(S) base URL"
            )
        self.solver_url = normalized_solver_url
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_candidates_per_run = max(1, int(max_candidates_per_run))

    async def handle(self, request: ChallengeRequest) -> ChallengeResult:
        if request.source != "immowelt-de":
            return ChallengeResult(action="defer", message="solver bridge only supports immowelt-de")
        if not _is_datadome_challenge(request):
            return ChallengeResult(
                action="defer",
                message="challenge is not positively identified as an Immowelt DataDome gate",
            )

        requested_url = str(request.challenge.get("requested_url") or "").strip()
        if _host(requested_url) not in IMMOWELT_HOSTS:
            return ChallengeResult(
                action="defer",
                message="Immowelt DataDome bridge requires an immowelt.de protected URL",
            )

        state_dir_raw = request.handoff_state.get("state_dir")
        if not state_dir_raw:
            return ChallengeResult(action="defer", message="challenge handoff has no state directory")
        state_dir = Path(str(state_dir_raw)).resolve()
        patch_path_raw = request.handoff_state.get("browser_patch_path")
        patch_path = (
            Path(str(patch_path_raw)).resolve()
            if patch_path_raw
            else (state_dir / "browser-patch.json").resolve()
        )
        # Older persisted handoffs predate browser_patch_path. Mutating the in-memory request
        # keeps them compatible with restore_challenge_handoff without rewriting run history.
        request.handoff_state["browser_patch_path"] = str(patch_path)
        try:
            patch_path.relative_to(state_dir)
        except ValueError:
            return ChallengeResult(action="defer", message="browser patch path escaped handoff state")

        run_state_path = state_dir.parent.parent / "datadome-solver-state.json"
        prior: dict[str, Any] = {}
        try:
            loaded_prior = json.loads(run_state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            loaded_prior = {}
        except (json.JSONDecodeError, OSError) as exc:
            return ChallengeResult(
                action="defer",
                message=f"invalid DataDome loop state: {type(exc).__name__}",
            )
        if not isinstance(loaded_prior, dict):
            return ChallengeResult(action="defer", message="invalid DataDome loop state object")
        prior = loaded_prior
        try:
            attempts = max(0, int(prior.get("candidate_count") or 0))
        except (TypeError, ValueError):
            return ChallengeResult(action="defer", message="invalid DataDome candidate counter")
        if attempts >= self.max_candidates_per_run:
            return ChallengeResult(
                action="defer",
                message="DataDome solver candidate limit reached; pausing instead of retry-looping",
            )

        try:
            result = await asyncio.to_thread(self._solve, requested_url)
        except SolverBridgeError as exc:
            return ChallengeResult(
                action="defer",
                message=f"local DataDome solver unavailable: {str(exc)[:300]}",
            )

        cookie_value = str(result.get("datadome_cookie") or "").strip()
        user_agent = str(result.get("user_agent") or "").strip()
        if result.get("proxy"):
            return ChallengeResult(
                action="defer",
                message="DataDome solver used a proxy; crawler replay would not share the exit IP",
            )
        if not result.get("solved") or not cookie_value or not user_agent:
            message = str(
                result.get("error") or "local DataDome solver returned no replayable clearance"
            )
            return ChallengeResult(action="defer", message=message[:400])

        cookie_domain = str(result.get("cookie_domain") or _host(requested_url)).strip().casefold()
        normalized_domain = cookie_domain.lstrip(".")
        if normalized_domain not in IMMOWELT_HOSTS and not normalized_domain.endswith(".immowelt.de"):
            return ChallengeResult(
                action="defer",
                message=f"solver returned unexpected DataDome cookie domain {cookie_domain!r}",
            )

        cookie_sha256 = hashlib.sha256(cookie_value.encode("utf-8")).hexdigest()
        if prior.get("last_cookie_sha256") == cookie_sha256:
            return ChallengeResult(
                action="defer",
                message="DataDome solver repeated the same clearance candidate; pausing retry loop",
            )

        max_age = result.get("cookie_max_age")
        try:
            expires = time.time() + max(0, int(max_age)) if max_age is not None else -1
        except (TypeError, ValueError):
            expires = -1

        patch = {
            "version": 1,
            "kind": "immowelt_datadome_clearance",
            "handoff_id": request.handoff_id,
            "protected_url": requested_url,
            "user_agent": user_agent,
            "cookie": {
                "name": "datadome",
                "value": cookie_value,
                "domain": cookie_domain or ".immowelt.de",
                "path": "/",
                "expires": expires,
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            },
        }
        _atomic_json(patch_path, patch)
        _atomic_json(
            run_state_path,
            {
                "version": 1,
                "candidate_count": attempts + 1,
                "last_cookie_sha256": cookie_sha256,
                "last_handoff_id": request.handoff_id,
            },
        )
        return ChallengeResult(
            action="resolved",
            message="DataDome clearance candidate staged for same-IP/exact-UA crawler replay",
        )


    def _solve(self, requested_url: str) -> dict[str, Any]:
        body = json.dumps(
            {
                "type": "datadome",
                "url": requested_url,
                "referer": "https://www.immowelt.de/",
                "timeout_s": min(60, max(5, int(self.timeout_seconds) - 5)),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            self.solver_url + "/solve",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            raise SolverBridgeError(f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SolverBridgeError(f"{type(exc).__name__}: {exc}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SolverBridgeError(f"invalid JSON response: {exc}") from exc
        if not isinstance(payload, dict):
            raise SolverBridgeError("solver response is not a JSON object")
        return payload


def configured_immowelt_challenge_handler(
    *,
    external_command: str | None,
    solver_url: str | None,
    timeout_seconds: float,
) -> ChallengeHandler | None:
    """Select the explicit operator command first, then the optional loopback bridge."""

    raw = str(external_command or "").strip()
    if raw:
        command = shlex.split(raw)
        if command:
            return ExternalCommandChallengeHandler(
                command,
                timeout_seconds=max(1.0, float(timeout_seconds)),
            )

    local_url = str(solver_url or "").strip()
    if not local_url:
        return None
    return ImmoweltDataDomeSolverHandler(
        local_url,
        timeout_seconds=min(90.0, max(5.0, float(timeout_seconds))),
    )
