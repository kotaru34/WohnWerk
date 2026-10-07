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




class DetailResponse:
    status = 200


class DetailPage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.frames = []

    async def goto(self, url: str, **_kwargs: object) -> DetailResponse:
        self.url = url
        return DetailResponse()

    async def content(self) -> str:
        return (
            "<html><body><h1>Einfamilienhaus zum Kauf</h1>"
            "<div>Heizungsart Ofen</div><div>Energieträger Öl</div>"
            "</body></html>"
        )

    async def wait_for_selector(self, selector: str, **_kwargs: object) -> None:
        assert selector == "h1"

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None

class HandoffContext:
    async def storage_state(self, *, path: str) -> None:
        Path(path).write_text('{"cookies": [], "origins": []}')


class HandoffPage:
    url = "https://www.immowelt.de/classified-search?page=2"

    async def evaluate(self, script: str):
        if script == "navigator.userAgent":
            return "headed-test-user-agent"
        assert "window.innerWidth" in script
        return {"width": 1280, "height": 720}

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
    assert not hasattr(fake.chromium.browser.context, "pattern")


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
    assert handoff["user_agent"] == "headed-test-user-agent"
    assert handoff["viewport"] == {"width": 1280, "height": 720}



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
            "state_dir": str(tmp_path),
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


@pytest.mark.asyncio
async def test_headed_adapter_preserves_manual_handoff_user_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage_state = tmp_path / "storage-state.json"
    storage_state.write_text('{"cookies":[],"origins":[]}\n')

    source = ImmoweltHeadedPropertySource()
    await source.restore_challenge_handoff(
        {
            "state_dir": str(tmp_path),
            "storage_state_path": str(storage_state),
            "user_agent": "manual-handoff-exact-ua",
            "viewport": {"width": 1440, "height": 900},
        }
    )

    fake = FakePlaywright()
    monkeypatch.setattr(headed_module, "async_playwright", lambda: FakeStarter(fake))
    await source._ensure_page()

    assert fake.chromium.browser.context_kwargs == {
        "locale": "de-DE",
        "viewport": {"width": 1440, "height": 900},
        "storage_state": str(storage_state),
        "user_agent": "manual-handoff-exact-ua",
    }


@pytest.mark.asyncio
async def test_headed_adapter_loads_exact_immowelt_detail_without_search_state_validation() -> None:
    source = ImmoweltHeadedPropertySource(request_delay_seconds=1.0)
    source._page = DetailPage()  # type: ignore[assignment]

    html, final_url = await source.load_detail_html(
        "https://www.immowelt.de/expose/3ab853e6-84ef-4ef8-9008-db1c98e76ed4"
    )

    assert final_url.endswith("3ab853e6-84ef-4ef8-9008-db1c98e76ed4")
    assert "Energieträger Öl" in html


@pytest.mark.asyncio
async def test_headed_adapter_rejects_non_immowelt_detail_url() -> None:
    source = ImmoweltHeadedPropertySource()

    with pytest.raises(ValueError, match="Unsupported Immowelt detail URL"):
        await source.load_detail_html("https://example.com/expose/not-allowed")


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_key", ["storage_state_path", "browser_patch_path", "screenshot_path"])
async def test_headed_adapter_rejects_foreign_handoff_paths(
    tmp_path: Path,
    foreign_key: str,
) -> None:
    state_dir = tmp_path / "handoff"
    state_dir.mkdir()
    storage_state = state_dir / "storage-state.json"
    storage_state.write_text('{"cookies":[],"origins":[]}\n')
    patch_path = state_dir / "browser-patch.json"
    handoff = {
        "state_dir": str(state_dir),
        "storage_state_path": str(storage_state),
        "browser_patch_path": str(patch_path),
        "screenshot_path": str(state_dir / "challenge.png"),
    }
    handoff[foreign_key] = str(tmp_path / "foreign-artifact")

    source = ImmoweltHeadedPropertySource()
    with pytest.raises(RuntimeError, match="escaped state directory"):
        await source.restore_challenge_handoff(handoff)


class _LiveLocator:
    async def count(self) -> int:
        return 1


class _LiveResumePage:
    def __init__(self, url: str) -> None:
        self.url = url
        self.frames = []
        self.goto_calls = 0
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    async def evaluate(self, script: str):
        if script == "navigator.userAgent":
            return "same-context-user-agent"
        return {"width": 1280, "height": 720}

    async def screenshot(self, *, path: str, full_page: bool) -> None:
        assert full_page is True
        Path(path).write_bytes(b"png")

    async def content(self) -> str:
        return (
            "<html><body><h1>1 Haus zum Kauf in Sachsen</h1>"
            '<div data-testid="serp-core-classified-card-testid"></div>'
            "</body></html>"
        )

    def locator(self, selector: str) -> _LiveLocator:
        assert selector == "h1"
        return _LiveLocator()

    async def goto(self, *_args, **_kwargs):
        self.goto_calls += 1
        raise AssertionError("same-context resume must not navigate again")

    async def close(self) -> None:
        self.closed = True


class _LiveResumeContext:
    def __init__(self) -> None:
        self.closed = False

    async def storage_state(self, *, path: str) -> None:
        Path(path).write_text('{"cookies":[],"origins":[]}\n')

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_live_handoff_resume_reuses_same_page_without_second_navigation(
    tmp_path: Path,
) -> None:
    source = ImmoweltHeadedPropertySource()
    requested_url = source._page_url("sachsen", "030000-099999", 1)
    page = _LiveResumePage(requested_url)
    context = _LiveResumeContext()
    source._page = page  # type: ignore[assignment]
    source._context = context  # type: ignore[assignment]
    challenge = SourceChallenge(
        "gate",
        challenge={
            "kind": "http_403",
            "requested_url": requested_url,
            "datadome_challenge_type": "fe",
        },
    )

    handoff = await source.prepare_challenge_handoff(
        state_dir=tmp_path / "run-1" / "handoff-1",
        challenge=challenge,
    )
    await source.restore_challenge_handoff(handoff)

    assert source._page is page
    assert source._context is context
    assert source._reuse_current_page_once is True
    assert page.closed is False
    assert context.closed is False

    html, final_url = await source._load_html(requested_url)

    assert final_url == requested_url
    assert "Haus zum Kauf" in html
    assert page.goto_calls == 0

    await source.aclose()
