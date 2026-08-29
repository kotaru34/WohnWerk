import pytest

from app import property_page_liveness as page_liveness


@pytest.mark.asyncio
async def test_house_page_tail_refresh_receives_only_rendered_property_ids(monkeypatch) -> None:
    captured: list[tuple[int, ...]] = []
    monkeypatch.setattr(
        page_liveness,
        "refresh_property_page_liveness",
        lambda property_ids: captured.append(property_ids),
    )

    async def app(_scope, _receive, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/html; charset=utf-8")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": (
                    b'<article id="house-7"></article>'
                    b'<article id="house-3"></article>'
                    b'<article id="house-7"></article>'
                ),
                "more_body": False,
            }
        )

    sent: list[dict] = []

    async def send(message) -> None:
        sent.append(message)

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    middleware = page_liveness.PropertyPageLivenessMiddleware(app)
    await middleware(
        {"type": "http", "path": "/houses"},
        receive,
        send,
    )

    assert len(sent) == 2
    assert captured == [(3, 7)]
