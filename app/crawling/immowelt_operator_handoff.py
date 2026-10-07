from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from app.crawling.challenge import ChallengeHandler, ChallengeRequest, ChallengeResult

DEFAULT_OPERATOR_ROOT = Path("/var/lib/wohnwerk/challenge-state/immowelt-de")
INTERACTIVE_DATADOME_TYPES = {"fe", "bv"}
IMMOWELT_HOSTS = {"immowelt.de", "www.immowelt.de"}
OPERATOR_SESSION_TTL = timedelta(minutes=15)
DEFAULT_OPERATOR_ARM_GRACE_SECONDS = 120.0
DEFAULT_OPERATOR_VIEWPORT = {"width": 1280, "height": 720}


@dataclass(slots=True)
class _LiveOperatorBrowserSession:
    context: Any
    page: Any


_LIVE_OPERATOR_BROWSER_SESSIONS: dict[str, _LiveOperatorBrowserSession] = {}


def _live_operator_session_key(state_dir: Path) -> str:
    return str(state_dir.resolve())


def register_live_operator_session(
    state_dir: Path,
    *,
    context: Any,
    page: Any,
) -> None:
    _LIVE_OPERATOR_BROWSER_SESSIONS[_live_operator_session_key(state_dir)] = (
        _LiveOperatorBrowserSession(context=context, page=page)
    )


def unregister_live_operator_session(
    state_dir: Path,
    *,
    page: Any | None = None,
) -> None:
    key = _live_operator_session_key(state_dir)
    current = _LIVE_OPERATOR_BROWSER_SESSIONS.get(key)
    if current is None:
        return
    if page is not None and current.page is not page:
        return
    _LIVE_OPERATOR_BROWSER_SESSIONS.pop(key, None)


def live_operator_session(state_dir: Path) -> _LiveOperatorBrowserSession | None:
    key = _live_operator_session_key(state_dir)
    current = _LIVE_OPERATOR_BROWSER_SESSIONS.get(key)
    if current is None:
        return None
    try:
        closed = bool(current.page.is_closed())
    except (AttributeError, TypeError):
        closed = False
    if closed:
        _LIVE_OPERATOR_BROWSER_SESSIONS.pop(key, None)
        return None
    return current


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _challenge_type_from_payload(payload: dict[str, Any]) -> str | None:
    challenge = payload.get("challenge")
    if not isinstance(challenge, dict):
        return None
    value = str(challenge.get("datadome_challenge_type") or "").strip().casefold()
    return value or None


def _state_dir_from_payload(payload: dict[str, Any]) -> Path:
    handoff = payload.get("handoff_state")
    if not isinstance(handoff, dict):
        raise TypeError("challenge handoff state is missing")
    raw = handoff.get("state_dir")
    if not raw:
        raise ValueError("challenge handoff state directory is missing")
    return Path(str(raw)).resolve()


def _run_dir(run_id: int, *, root: Path = DEFAULT_OPERATOR_ROOT) -> Path:
    return (root / f"run-{int(run_id)}").resolve()


def operator_run_dir(run_id: int, *, root: Path = DEFAULT_OPERATOR_ROOT) -> Path:
    return _run_dir(run_id, root=root)


def validate_state_dir(
    run_id: int,
    state_dir: Path,
    *,
    root: Path = DEFAULT_OPERATOR_ROOT,
) -> tuple[Path, Path]:
    state_dir = state_dir.resolve()
    run_dir = _run_dir(run_id, root=root)
    try:
        state_dir.relative_to(run_dir)
    except ValueError as exc:
        raise ValueError("challenge handoff state escaped the expected Immowelt run directory") from exc
    return state_dir, run_dir


def challenge_state_for_run(
    run_id: int,
    active_challenge: dict[str, Any],
    *,
    root: Path = DEFAULT_OPERATOR_ROOT,
) -> tuple[Path, Path]:
    return validate_state_dir(run_id, _state_dir_from_payload(active_challenge), root=root)


def operator_status_path(run_dir: Path) -> Path:
    return run_dir / "operator-status.json"


def operator_frame_path(run_dir: Path) -> Path:
    return run_dir / "operator-frame.png"


def operator_events_path(run_dir: Path) -> Path:
    return run_dir / "operator-events.jsonl"


def operator_approval_path(run_dir: Path) -> Path:
    return run_dir / "operator-approval.json"


def prepare_fresh_operator_reverification(
    run_id: int,
    active_challenge: dict[str, Any],
    *,
    root: Path = DEFAULT_OPERATOR_ROOT,
) -> int:
    """Drop only stale Immowelt DataDome clearance before explicit human re-verification.

    All other persisted browser state is preserved. This is used only when an operator
    explicitly arms a paused interactive challenge and no live browser process is waiting.
    """
    if _challenge_type_from_payload(active_challenge) not in INTERACTIVE_DATADOME_TYPES:
        raise ValueError("active challenge is not an interactive Immowelt DataDome verification")

    state_dir, _run_dir = challenge_state_for_run(run_id, active_challenge, root=root)
    storage_state_path = state_dir / "storage-state.json"
    state = _read_json(storage_state_path)
    if state is None:
        raise ValueError("challenge storage state is missing or invalid")

    raw_cookies = state.get("cookies")
    if not isinstance(raw_cookies, list):
        raise ValueError("challenge storage state cookies are invalid")

    removed = 0
    cookies: list[Any] = []
    for item in raw_cookies:
        if not isinstance(item, dict) or item.get("name") != "datadome":
            cookies.append(item)
            continue
        domain = str(item.get("domain") or "").casefold().lstrip(".")
        if domain in IMMOWELT_HOSTS or domain.endswith(".immowelt.de"):
            removed += 1
            continue
        cookies.append(item)

    if removed:
        state["cookies"] = cookies
        _atomic_json(storage_state_path, state)
    return removed


def arm_operator_handoff(
    run_id: int,
    active_challenge: dict[str, Any],
    *,
    root: Path = DEFAULT_OPERATOR_ROOT,
    now: datetime | None = None,
) -> Path:
    if _challenge_type_from_payload(active_challenge) not in INTERACTIVE_DATADOME_TYPES:
        raise ValueError("active challenge is not an interactive Immowelt DataDome verification")

    _state_dir, run_dir = challenge_state_for_run(run_id, active_challenge, root=root)
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_dir.chmod(0o700)
    now = (now or datetime.now(UTC)).astimezone(UTC)
    approval = {
        "version": 1,
        "run_id": int(run_id),
        "armed_at": now.isoformat(),
        "expires_at": (now + OPERATOR_SESSION_TTL).isoformat(),
    }
    _atomic_json(operator_approval_path(run_dir), approval)
    for path in (operator_status_path(run_dir), operator_events_path(run_dir), operator_frame_path(run_dir)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return run_dir


def read_operator_status(
    run_dir: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = _read_json(operator_status_path(run_dir))
    if payload is not None:
        return payload
    approval = _read_json(operator_approval_path(run_dir))
    if approval is not None:
        try:
            run_id = int(approval.get("run_id"))
        except (TypeError, ValueError):
            return {"state": "invalid"}
        if _approval_is_active(run_id, run_dir, now=now):
            return {"state": "armed", "run_id": run_id}
        return {"state": "expired", "run_id": run_id}
    return {"state": "idle"}


def enqueue_operator_pointer(
    run_dir: Path,
    *,
    phase: str,
    x: float = 0.0,
    y: float = 0.0,
) -> None:
    if phase not in {"down", "move", "up", "cancel"}:
        raise ValueError("unsupported operator pointer phase")
    if phase != "cancel" and not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError("operator pointer coordinates must be normalized")
    event = {
        "at": datetime.now(UTC).isoformat(),
        "phase": phase,
        "x": float(x),
        "y": float(y),
    }
    path = operator_events_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    path.chmod(0o600)


def _operator_viewport(handoff_state: dict[str, Any]) -> dict[str, int]:
    raw = handoff_state.get("viewport")
    if isinstance(raw, dict):
        try:
            width = int(raw.get("width"))
            height = int(raw.get("height"))
        except (TypeError, ValueError):
            width = height = 0
        if 320 <= width <= 4096 and 240 <= height <= 2160:
            return {"width": width, "height": height}
    return dict(DEFAULT_OPERATOR_VIEWPORT)


def _approval_is_active(run_id: int, run_dir: Path, *, now: datetime | None = None) -> bool:
    payload = _read_json(operator_approval_path(run_dir))
    if payload is None or payload.get("version") != 1:
        return False
    try:
        if int(payload.get("run_id")) != int(run_id):
            return False
        expires = datetime.fromisoformat(str(payload.get("expires_at")))
    except (TypeError, ValueError):
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)).astimezone(UTC) < expires.astimezone(UTC)


async def _has_immowelt_datadome_cookie(context: Any) -> bool:
    cookies = await context.cookies()
    for cookie in cookies:
        if cookie.get("name") != "datadome" or not cookie.get("value"):
            continue
        domain = str(cookie.get("domain") or "").casefold().lstrip(".")
        if domain in IMMOWELT_HOSTS or domain.endswith(".immowelt.de"):
            return True
    return False


def _finish_operator_state(run_dir: Path, *, state: str, message: str) -> None:
    _atomic_json(
        operator_status_path(run_dir),
        {
            "version": 1,
            "state": state,
            "message": message,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
    try:
        operator_approval_path(run_dir).unlink()
    except FileNotFoundError:
        pass


class ImmoweltOperatorChallengeHandler(ChallengeHandler):
    """Human-in-the-loop remote pointer handoff for interactive Immowelt DataDome gates.

    The handler automates browser/session lifecycle only. It never computes or replays a
    slider trajectory. Pointer events are accepted solely from the authenticated WohnWerk
    admin UI and forwarded verbatim to the challenge page.
    """

    def __init__(
        self,
        fallback: ChallengeHandler,
        *,
        timeout_seconds: float = 900.0,
        arm_grace_seconds: float = DEFAULT_OPERATOR_ARM_GRACE_SECONDS,
        root: Path = DEFAULT_OPERATOR_ROOT,
    ) -> None:
        self.fallback = fallback
        self.timeout_seconds = max(30.0, float(timeout_seconds))
        self.arm_grace_seconds = max(0.0, float(arm_grace_seconds))
        self.root = root

    async def handle(self, request: ChallengeRequest) -> ChallengeResult:
        challenge_type = str(
            request.challenge.get("datadome_challenge_type") or ""
        ).strip().casefold()
        if request.source != "immowelt-de" or challenge_type not in INTERACTIVE_DATADOME_TYPES:
            return await self.fallback.handle(request)

        state_dir_raw = request.handoff_state.get("state_dir")
        if not state_dir_raw:
            return await self.fallback.handle(request)
        try:
            state_dir, run_dir = validate_state_dir(
                request.run_id,
                Path(str(state_dir_raw)),
                root=self.root,
            )
        except ValueError:
            return ChallengeResult(action="defer", message="invalid operator handoff state directory")

        live_session = live_operator_session(state_dir)
        if not _approval_is_active(request.run_id, run_dir):
            if live_session is None or self.arm_grace_seconds <= 0:
                return await self.fallback.handle(request)

            _atomic_json(
                operator_status_path(run_dir),
                {
                    "version": 1,
                    "state": "awaiting_approval",
                    "run_id": request.run_id,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
            approval_deadline = time.monotonic() + self.arm_grace_seconds
            while time.monotonic() < approval_deadline:
                if _approval_is_active(request.run_id, run_dir):
                    live_session = live_operator_session(state_dir)
                    if live_session is not None:
                        break
                    return await self.fallback.handle(request)
                await asyncio.sleep(0.25)
            else:
                _atomic_json(
                    operator_status_path(run_dir),
                    {
                        "version": 1,
                        "state": "approval_timeout",
                        "run_id": request.run_id,
                        "updated_at": datetime.now(UTC).isoformat(),
                    },
                )
                return await self.fallback.handle(request)

        return await self._run_session(
            request,
            state_dir=state_dir,
            run_dir=run_dir,
            live_session=live_session,
        )

    async def _run_session(
        self,
        request: ChallengeRequest,
        *,
        state_dir: Path,
        run_dir: Path,
        live_session: _LiveOperatorBrowserSession | None = None,
    ) -> ChallengeResult:
        storage_state_path = state_dir / "storage-state.json"
        frame_path = operator_frame_path(run_dir)
        events_path = operator_events_path(run_dir)
        requested_url = str(request.challenge.get("requested_url") or "").strip()
        if (urlparse(requested_url).hostname or "").casefold() not in IMMOWELT_HOSTS:
            _finish_operator_state(
                run_dir,
                state="deferred",
                message="interactive handoff requires an immowelt.de protected URL",
            )
            return ChallengeResult(
                action="defer",
                message="interactive handoff requires an immowelt.de protected URL",
            )

        display = os.environ.get("DISPLAY") or os.environ.get(
            "WOHNWERK_IMMOWELT_OPERATOR_DISPLAY",
            ":97",
        )
        owns_browser = live_session is None
        playwright = browser = None
        context = live_session.context if live_session is not None else None
        page = live_session.page if live_session is not None else None
        event_offset = 0
        started = time.monotonic()
        last_frame = 0.0
        try:
            viewport = _operator_viewport(request.handoff_state)
            if owns_browser:
                playwright = await async_playwright().start()
                browser = await playwright.chromium.launch(
                    headless=False,
                    args=["--disable-crash-reporter"],
                    env={**os.environ, "DISPLAY": display},
                )
                context_kwargs: dict[str, Any] = {
                    "locale": "de-DE",
                    "viewport": dict(viewport),
                }
                handoff_user_agent = str(
                    request.handoff_state.get("user_agent") or ""
                ).strip()
                if handoff_user_agent:
                    context_kwargs["user_agent"] = handoff_user_agent
                if storage_state_path.is_file():
                    context_kwargs["storage_state"] = str(storage_state_path)
                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()
                try:
                    await page.goto(
                        requested_url,
                        wait_until="domcontentloaded",
                        timeout=45_000,
                    )
                except PlaywrightError:
                    pass
            if context is None or page is None:
                raise RuntimeError("operator handoff browser session is unavailable")

            _atomic_json(
                operator_status_path(run_dir),
                {
                    "version": 1,
                    "state": "active",
                    "run_id": request.run_id,
                    "started_at": datetime.now(UTC).isoformat(),
                    "viewport": dict(viewport),
                },
            )

            while time.monotonic() - started < self.timeout_seconds:
                if events_path.is_file():
                    with events_path.open("r", encoding="utf-8") as handle:
                        handle.seek(event_offset)
                        lines = handle.readlines()
                        event_offset = handle.tell()
                    for line in lines:
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(event, dict):
                            continue
                        phase = str(event.get("phase") or "")
                        if phase == "cancel":
                            _finish_operator_state(
                                run_dir,
                                state="cancelled",
                                message="operator cancelled interactive verification",
                            )
                            return ChallengeResult(
                                action="defer",
                                message="operator cancelled interactive verification",
                            )
                        if phase not in {"down", "move", "up"}:
                            continue
                        try:
                            x = float(event.get("x")) * viewport["width"]
                            y = float(event.get("y")) * viewport["height"]
                        except (TypeError, ValueError):
                            continue
                        x = min(max(x, 0.0), float(viewport["width"] - 1))
                        y = min(max(y, 0.0), float(viewport["height"] - 1))
                        await page.mouse.move(x, y)
                        if phase == "down":
                            await page.mouse.down(button="left")
                        elif phase == "up":
                            await page.mouse.up(button="left")

                now = time.monotonic()
                if now - last_frame >= 0.45:
                    tmp_frame = frame_path.with_suffix(".tmp.png")
                    try:
                        await page.screenshot(path=str(tmp_frame), full_page=False)
                        tmp_frame.chmod(0o600)
                        os.replace(tmp_frame, frame_path)
                    except PlaywrightError:
                        try:
                            tmp_frame.unlink()
                        except FileNotFoundError:
                            pass
                    last_frame = now

                frame_urls = [frame.url for frame in page.frames]
                challenge_present = any(
                    "captcha-delivery.com/captcha/" in url
                    or "captcha-delivery.net/captcha/" in url
                    for url in frame_urls
                )
                page_host = (urlparse(page.url).hostname or "").casefold()

                clearance_present = await _has_immowelt_datadome_cookie(context)
                content_present = await page.locator("h1").count() > 0

                _atomic_json(
                    operator_status_path(run_dir),
                    {
                        "version": 1,
                        "state": "active",
                        "run_id": request.run_id,
                        "updated_at": datetime.now(UTC).isoformat(),
                        "page_url": page.url,
                        "challenge_present": challenge_present,
                        "clearance_present": clearance_present,
                        "content_present": content_present,
                        "viewport": dict(viewport),
                    },
                )
                if (
                    not challenge_present
                    and page_host in IMMOWELT_HOSTS
                    and clearance_present
                    and content_present
                ):
                    await context.storage_state(path=str(storage_state_path))
                    storage_state_path.chmod(0o600)
                    _finish_operator_state(
                        run_dir,
                        state="resolved",
                        message="operator completed interactive DataDome verification",
                    )
                    return ChallengeResult(
                        action="resolved",
                        message="operator completed interactive DataDome verification",
                    )

                await asyncio.sleep(0.25)

            _finish_operator_state(
                run_dir,
                state="timeout",
                message="operator handoff timed out without completed verification",
            )
            return ChallengeResult(
                action="defer",
                message="operator handoff timed out without completed verification",
            )
        except (OSError, PlaywrightError) as exc:
            _finish_operator_state(
                run_dir,
                state="deferred",
                message=f"operator handoff browser failed: {type(exc).__name__}",
            )
            return ChallengeResult(
                action="defer",
                message=f"operator handoff browser failed: {type(exc).__name__}",
            )
        finally:
            if owns_browser:
                if page is not None:
                    await page.close()
                if context is not None:
                    await context.close()
                if browser is not None:
                    await browser.close()
                if playwright is not None:
                    await playwright.stop()
