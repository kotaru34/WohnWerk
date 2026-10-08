from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.crawling.immowelt_access import immowelt_access_restricted
from app.crawling.immowelt_operator_handoff import (
    ImmoweltOperatorChallengeHandler,
    _has_verified_search_results,
    _operator_page_has_access_restriction,
    operator_run_dir,
    read_operator_status,
)
from app.sources.property.immowelt_de import detect_immowelt_challenge

BLOCK_TEXT = (
    "Der Zugriff ist vorübergehend eingeschränkt\n"
    "Warum diese Blockade? Etwas im Verhalten des Browsers hat uns stutzig gemacht.\n"
    "Probleme beim Zugriff auf die Website? Wenden Sie sich an den Support"
)


def test_immowelt_block_classification_is_specific() -> None:
    assert immowelt_access_restricted(BLOCK_TEXT)
    assert immowelt_access_restricted("Your access has been temporarily restricted")
    assert not immowelt_access_restricted("Ich bin kein Roboter. Bitte bestätigen.")
    assert not immowelt_access_restricted("42 Häuser zum Kauf in Brandenburg")


def test_provider_block_detected_even_on_http_200_without_captcha_iframe() -> None:
    gate = detect_immowelt_challenge(
        status=200,
        requested_url="https://www.immowelt.de/classified-search?page=1",
        final_url="https://www.immowelt.de/classified-search?page=1",
        html=f"<html><body><h1>{BLOCK_TEXT}</h1></body></html>",
    )
    assert gate is not None
    assert gate["kind"] == "provider_access_restricted"
    assert gate["markers"] == ["immowelt_access_restricted"]


class _Body:
    def __init__(self, value: str) -> None:
        self.value = value

    async def inner_text(self, *, timeout: int) -> str:
        assert timeout == 200
        return self.value


class _Frame:
    def __init__(self, text: str) -> None:
        self.text = text

    def locator(self, selector: str) -> _Body:
        assert selector == "body"
        return _Body(self.text)


@pytest.mark.asyncio
async def test_operator_detects_block_inside_frame_after_slider() -> None:
    page = SimpleNamespace(
        frames=[_Frame(BLOCK_TEXT)],
        locator=lambda selector: _Frame("42 Häuser zum Kauf").locator(selector),
    )
    assert await _operator_page_has_access_restriction(page)


@pytest.mark.asyncio
async def test_operator_stops_on_terminal_access_block_without_forged_clearance(
    tmp_path,
) -> None:
    root = tmp_path / "operator"
    state_dir = root / "run-123" / "shard-7" / "handoff-1"
    state_dir.mkdir(parents=True)
    (state_dir / "storage-state.json").write_text('{"cookies":[],"origins":[]}')
    from app.crawling.challenge import ChallengeRequest

    request = ChallengeRequest(
        source="immowelt-de",
        run_id=123,
        shard_id=7,
        shard_key="test",
        shard_params={},
        mode="incremental",
        reason="DataDome gate",
        challenge={
            "requested_url": "https://www.immowelt.de/classified-search?page=1",
            "datadome_challenge_type": "fe",
        },
        resume_cursor={"resume_page": 1},
        handoff_state={"state_dir": str(state_dir)},
    )

    class Page:
        def __init__(self) -> None:
            self.url = request.challenge["requested_url"]
            self.frames = [_Frame(BLOCK_TEXT)]

        def locator(self, selector):
            return _Frame("42 Häuser zum Kauf").locator(selector)

        async def screenshot(self, *, path, full_page):
            assert full_page is False
            from pathlib import Path

            Path(path).write_bytes(b"frame")

    class Context:
        async def cookies(self):
            return [{"name": "datadome", "value": "nonempty", "domain": ".immowelt.de"}]

        async def storage_state(self, **kwargs):
            raise AssertionError("Do not treat upstream block as resolved")

    class Fallback:
        async def handle(self, request):
            raise AssertionError("Should not invoke fallback for the block")

    handler = ImmoweltOperatorChallengeHandler(Fallback(), root=root)
    result = await handler._run_session(
        request,
        state_dir=state_dir,
        run_dir=operator_run_dir(123, root=root),
        live_session=SimpleNamespace(context=Context(), page=Page()),
    )
    assert result.action == "defer"
    assert "provider access restricted" in (result.message or "")
    assert read_operator_status(operator_run_dir(123, root=root))["state"] == "blocked"


class _HeadingLocator:
    def __init__(self, heading: str) -> None:
        self.heading = heading

    @property
    def first(self):
        return self

    async def inner_text(self, *, timeout: int) -> str:
        assert timeout == 1000
        return self.heading


class _SearchPage:
    def __init__(self, url: str, heading: str) -> None:
        self.url = url
        self.heading = heading

    def locator(self, selector: str) -> _HeadingLocator:
        assert selector == "h1"
        return _HeadingLocator(self.heading)


@pytest.mark.asyncio
async def test_operator_requires_real_search_state_not_generic_h1() -> None:
    from app.sources.property.immowelt_de import ImmoweltGermanyPropertySource

    source = ImmoweltGermanyPropertySource()
    url = source._page_url("sachsen", "030000-099999", 1)

    assert await _has_verified_search_results(
        _SearchPage(url, "42 Häuser zum Kauf in Sachsen"), url
    )
    assert not await _has_verified_search_results(
        _SearchPage(url, BLOCK_TEXT), url
    )
    assert not await _has_verified_search_results(
        _SearchPage("https://www.immowelt.de/", "42 Häuser zum Kauf in Sachsen"), url
    )
    assert not await _has_verified_search_results(
        _SearchPage(url.replace("priceMin=30000", "priceMin=100000"), "42 Häuser zum Kauf"), url
    )
