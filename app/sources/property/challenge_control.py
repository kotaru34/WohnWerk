from __future__ import annotations

import importlib
import inspect
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from playwright.async_api import BrowserContext, Page


class ChallengeAction(StrEnum):
    RESUME = "resume"
    DEFER = "defer"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class ChallengeRequest:
    source_name: str
    run_id: int
    shard_key: str
    bundesland_key: str
    price_band_key: str
    page_number: int
    requested_url: str
    final_url: str
    reason: str
    http_status: int | None
    storage_state_path: str | None
    attempt: int


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    action: ChallengeAction
    message: str | None = None


class ChallengeHandler(Protocol):
    def __call__(
        self,
        request: ChallengeRequest,
        *,
        page: Page,
        browser_context: BrowserContext,
    ) -> ChallengeResult | ChallengeAction | str | bool | Awaitable[ChallengeResult | ChallengeAction | str | bool]: ...


def _normalize_result(value: ChallengeResult | ChallengeAction | str | bool) -> ChallengeResult:
    if isinstance(value, ChallengeResult):
        return value
    if isinstance(value, ChallengeAction):
        return ChallengeResult(action=value)
    if value is True:
        return ChallengeResult(action=ChallengeAction.RESUME)
    if value is False:
        return ChallengeResult(action=ChallengeAction.DEFER)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        for action in ChallengeAction:
            if normalized == action.value:
                return ChallengeResult(action=action)
    raise TypeError(
        "challenge handler must return ChallengeResult, ChallengeAction, "
        "'resume'/'defer'/'fail', or bool"
    )


def load_challenge_handler(spec: str | None = None) -> ChallengeHandler | None:
    """Load an operator-provided handler without implementing challenge completion here.

    The handler path is ``module:attribute``. WohnWerk owns the handoff/resume state
    machine only; the implementation behind this interface is external to this module.
    """
    raw = (spec or os.getenv("WOHNWERK_IMMOWELT_CHALLENGE_HANDLER") or "").strip()
    if not raw:
        return None
    module_name, separator, attribute = raw.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("challenge handler must use module:attribute syntax")
    module = importlib.import_module(module_name)
    handler = getattr(module, attribute)
    if not callable(handler):
        raise TypeError(f"challenge handler {raw!r} is not callable")
    return handler


async def invoke_challenge_handler(
    handler: ChallengeHandler,
    request: ChallengeRequest,
    *,
    page: Page,
    browser_context: BrowserContext,
) -> ChallengeResult:
    value: Any = handler(request, page=page, browser_context=browser_context)
    if inspect.isawaitable(value):
        value = await value
    return _normalize_result(value)


async def persist_browser_state(
    browser_context: BrowserContext,
    path: str | Path | None,
) -> str | None:
    if path is None:
        return None
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    await browser_context.storage_state(path=str(target))
    return str(target)
