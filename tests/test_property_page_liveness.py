import pytest

from app import property_page_liveness as page_liveness
from app.models import PropertyListing
from app.property_liveness import PropertyLivenessProbe


def test_direct_source_unknown_does_not_hide_visible_listing() -> None:
    listing = PropertyListing(
        raw_payload={
            "product_visible": True,
            "product_visibility_reason": "accepted",
        }
    )

    page_liveness._apply_direct_source_probe(
        listing,
        PropertyLivenessProbe("unknown", 429, "http_429"),
    )

    assert listing.raw_payload["product_visible"] is True
    assert listing.raw_payload["product_visibility_reason"] == "accepted"
    assert listing.raw_payload["page_liveness_state"] == "unknown"


def test_direct_source_definitive_dead_hides_listing() -> None:
    listing = PropertyListing(
        raw_payload={
            "product_visible": True,
            "product_visibility_reason": "accepted",
        }
    )

    page_liveness._apply_direct_source_probe(
        listing,
        PropertyLivenessProbe("dead", 404, "http_404"),
    )

    assert listing.raw_payload["product_visible"] is False
    assert listing.raw_payload["product_visibility_reason"] == "source_dead"
    assert listing.raw_payload["page_liveness_state"] == "dead"


@pytest.mark.asyncio
async def test_house_page_tail_refresh_receives_only_rendered_property_ids(monkeypatch) -> None:
    captured: list[tuple[int, ...]] = []
    monkeypatch.setattr(
        page_liveness,
        "_schedule_property_page_liveness",
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
