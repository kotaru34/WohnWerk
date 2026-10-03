from __future__ import annotations

from pathlib import Path

import pytest

import app.sources.property.immowelt_de_headed as headed_module
from app.sources.base import SourceChallenge
from app.sources.property.immowelt_de_headed import ImmoweltHeadedPropertySource


class FakeRouteTarget:
    async def route(self, pattern: str, handler: object) -> None:
        self.pattern = pattern
        self.handler = handler

    async def new_page(self) -> object:
        return object()


class FakeBrowser:
    def __init__(self) -> None:
        self.context = FakeRouteTarget()
        self.context_kwargs: dict[str, object] | None = None

    async def new_context(self, **kwargs: object) -> FakeRouteTarget:
        self.context_kwargs = kwargs
        return self.context


class FakeChromium:
    def __init__(self) -> None:
        self.launch_kwargs: dict[str, object] | None = None
        self.browser = FakeBrowser()

    async def launch(self, **kwargs: object) -> FakeBrowser:
        self.launch_kwargs = kwargs
        return self.browser


class FakePlaywright:
    def __init__(self) -> None:
        self.chromium = FakeChromium()


class FakeStarter:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright

    async def start(self) -> FakePlaywright:
        return self.playwright


class HandoffContext:
    async def storage_state(self, *, path: str) -> None:
        Path(path).write_text('{"cookies": [], "origins": []}')


class HandoffPage:
    url = "https://www.immowelt.de/classified-search?page=2"

    async def screenshot(self, *, path: str, full_page: bool) -> None:
        assert full_page is True
        Path(path).write_bytes(b"png")


@pytest.mark.asyncio
async def test_immowelt_launches_plain_headed_chromium(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePlaywright()
    monkeypatch.setattr(
        headed_module,
        "async_playwright",
        lambda: FakeStarter(fake),
    )

    source = ImmoweltHeadedPropertySource()
    page = await source._ensure_page()

    assert page is not None
    assert fake.chromium.launch_kwargs == {
        "headless": False,
        "args": ["--disable-crash-reporter"],
    }
    assert fake.chromium.browser.context_kwargs == {"locale": "de-DE"}
    assert fake.chromium.browser.context.pattern == "**/*"


def test_headed_adapter_keeps_confirmed_direct_search_urls() -> None:
    source = ImmoweltHeadedPropertySource()
    url = source._page_url("sachsen", "030000-099999", 1)

    assert url.startswith("https://www.immowelt.de/classified-search?")
    assert "locations=AD04DE14" in url
    assert "priceMin=30000" in url
    assert "priceMax=99999" in url
    assert "order=DateDesc" in url
    assert "page=1" in url


@pytest.mark.asyncio
async def test_headed_adapter_exports_browser_state_for_external_handler(tmp_path) -> None:
    source = ImmoweltHeadedPropertySource()
    source._context = HandoffContext()  # type: ignore[assignment]
    source._page = HandoffPage()  # type: ignore[assignment]
    challenge = SourceChallenge("gate", challenge={"kind": "http_403", "page": 2})

    handoff = await source.prepare_challenge_handoff(
        state_dir=tmp_path / "handoff",
        challenge=challenge,
    )

    assert Path(handoff["storage_state_path"]).is_file()
    assert Path(handoff["screenshot_path"]).is_file()
    assert handoff["browser_patch_path"].endswith("browser-patch.json")
    assert handoff["current_url"].endswith("page=2")
    assert handoff["challenge"]["kind"] == "http_403"



@pytest.mark.asyncio
async def test_headed_adapter_applies_datadome_patch_to_recreated_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    storage_state = tmp_path / "storage-state.json"
    storage_state.write_text(
        '{"cookies":['
        '{"name":"datadome","value":"stale-a","domain":"www.immowelt.de","path":"/"},'
        '{"name":"datadome","value":"stale-b","domain":".immowelt.de","path":"/"},'
        '{"name":"other","value":"keep","domain":".immowelt.de","path":"/"}'
        '],"origins":[]}'
    )
    patch_path = tmp_path / "browser-patch.json"
    patch_path.write_text(
        '{"version":1,"kind":"immowelt_datadome_clearance",'
        '"user_agent":"solver-exact-ua",'
        '"cookie":{"name":"datadome","value":"clearance","domain":".immowelt.de",'
        '"path":"/","expires":-1,"httpOnly":false,"secure":true,"sameSite":"Lax"}}'
    )

    source = ImmoweltHeadedPropertySource()
    await source.restore_challenge_handoff(
        {
            "storage_state_path": str(storage_state),
            "browser_patch_path": str(patch_path),
        }
    )

    state = __import__("json").loads(storage_state.read_text())
    assert state["cookies"] == [
        {
            "name": "other",
            "value": "keep",
            "domain": ".immowelt.de",
            "path": "/",
        },
        {
            "name": "datadome",
            "value": "clearance",
            "domain": ".immowelt.de",
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": True,
            "sameSite": "Lax",
        },
    ]
    assert not patch_path.exists()

    fake = FakePlaywright()
    monkeypatch.setattr(headed_module, "async_playwright", lambda: FakeStarter(fake))
    await source._ensure_page()

    assert fake.chromium.browser.context_kwargs == {
        "locale": "de-DE",
        "storage_state": str(storage_state),
        "user_agent": "solver-exact-ua",
    }
