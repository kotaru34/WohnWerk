from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ChallengeRequest:
    """Serializable handoff contract for an operator-provided challenge handler.

    WohnWerk owns crawl orchestration and persistence. The handler is intentionally an
    external boundary: it may inspect the supplied state and return a disposition, while
    no challenge-solving implementation lives in the WohnWerk codebase.
    """

    source: str
    run_id: int
    shard_id: int
    shard_key: str
    shard_params: dict[str, Any]
    mode: str
    reason: str
    challenge: dict[str, Any]
    resume_cursor: dict[str, Any]
    handoff_state: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    action: str
    message: str | None = None
    retry_after_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.action not in {"resolved", "defer", "abort"}:
            raise ValueError(f"Unsupported challenge action: {self.action!r}")
        if self.retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must not be negative")


class ChallengeHandler(Protocol):
    async def handle(self, request: ChallengeRequest) -> ChallengeResult:
        """Return resolved, defer, or abort for one persisted challenge handoff."""


class DeferredChallengeHandler:
    """Default fail-closed handler used when no external handler is configured."""

    async def handle(self, request: ChallengeRequest) -> ChallengeResult:
        del request
        return ChallengeResult(
            action="defer",
            message="no user-provided challenge handler configured",
        )


class ExternalCommandChallengeHandler:
    """Invoke a user-provided executable using a small JSON stdin/stdout contract.

    The command is executed directly (never through a shell). WohnWerk does not interpret
    or implement the handler's challenge-solving logic; it only supplies persisted crawl
    context and consumes the handler's disposition.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float = 900.0,
    ) -> None:
        normalized = tuple(str(part) for part in command if str(part))
        if not normalized:
            raise ValueError("challenge handler command must not be empty")
        self.command = normalized
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    async def handle(self, request: ChallengeRequest) -> ChallengeResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdin = (json.dumps(request.to_payload(), ensure_ascii=False) + "\n").encode()
            stdout, stderr = await asyncio.wait_for(
                process.communicate(stdin),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            try:
                process.kill()
                await process.wait()
            except (NameError, ProcessLookupError):
                pass
            return ChallengeResult(
                action="defer",
                message="user challenge handler timed out",
            )
        except OSError as exc:
            return ChallengeResult(
                action="defer",
                message=f"user challenge handler could not start: {type(exc).__name__}: {exc}",
            )

        stderr_text = stderr.decode(errors="replace").strip()
        if process.returncode != 0:
            message = f"user challenge handler exited rc={process.returncode}"
            if stderr_text:
                message += f": {stderr_text[:500]}"
            return ChallengeResult(action="defer", message=message)

        try:
            payload = json.loads(stdout.decode())
            if not isinstance(payload, dict):
                raise TypeError("handler response must be a JSON object")
            action = str(payload.get("action") or "")
            message_value = payload.get("message")
            message = None if message_value is None else str(message_value)
            retry_after = float(payload.get("retry_after_seconds") or 0.0)
            return ChallengeResult(
                action=action,
                message=message,
                retry_after_seconds=retry_after,
            )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return ChallengeResult(
                action="defer",
                message=f"invalid user challenge handler response: {type(exc).__name__}: {exc}",
            )
