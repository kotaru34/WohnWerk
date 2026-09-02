from decimal import Decimal

from app.models import PropertyListing
from app.property_acquisition import annotate_property_items_by_budget
from app.property_liveness import (
    PROPERTY_LIVENESS_RECHECK_HOURS,
    PropertyLivenessProbe,
    _apply_persisted_probe,
    assess_property_page,
    assess_property_redirect,
)
from app.sources.base import RawProperty


def _item(payload: dict) -> RawProperty:
    return RawProperty(
        source_listing_id="listing-1",
        url="https://portal.example/expose/1",
        title="Haus mit Garten",
        price_eur=Decimal(150000),
        postal_code="8010",
        city="Graz",
        raw_payload=payload,
    )


def test_synthetic_crawler_identity_is_never_product_visible() -> None:
    item = _item({"original_url_missing": True, "identity_stable": False})

    annotate_property_items_by_budget([item])

    assert item.raw_payload["product_visible"] is False
    assert item.raw_payload["product_visibility_reason"] == "source_url_missing"


def test_required_live_source_is_product_visible() -> None:
    item = _item(
        {
            "original_url_missing": False,
            "source_liveness_required": True,
            "source_liveness_state": "live",
        }
    )

    annotate_property_items_by_budget([item])

    assert item.raw_payload["product_visible"] is True
    assert item.raw_payload["product_visibility_reason"] == "accepted"


def test_required_dead_or_unverified_source_is_hidden() -> None:
    dead = _item(
        {
            "source_liveness_required": True,
            "source_liveness_state": "dead",
        }
    )
    unknown = _item(
        {
            "source_liveness_required": True,
            "source_liveness_state": "unknown",
        }
    )

    annotate_property_items_by_budget([dead, unknown])

    assert dead.raw_payload["product_visible"] is False
    assert dead.raw_payload["product_visibility_reason"] == "source_dead"
    assert unknown.raw_payload["product_visible"] is False
    assert unknown.raw_payload["product_visibility_reason"] == "source_liveness_unverified"


def test_dibeo_removed_placeholder_is_dead() -> None:
    state, reason = assess_property_page(
        200,
        "Diese Immobilie wurde schon gefunden - aber auf dibeo.at warten andere Angebote.",
    )

    assert state == "dead"
    assert reason == "dibeo_already_found"


def test_dibeo_entity_removed_redirect_is_dead_before_captcha_body() -> None:
    assessment = assess_property_redirect(
        "https://www.dibeo.at/a/riv/a?utm_source=IMMMO&entityRemoved=1"
    )

    assert assessment == ("dead", "dibeo_entity_removed")
    assert assess_property_redirect("https://www.dibeo.at/expose/2229425") is None
    assert (
        assess_property_redirect("https://other.example/a/riv/a?entityRemoved=1") is None
    )


def test_http_liveness_is_conservative() -> None:
    assert assess_property_page(404, "") == ("dead", "http_404")
    assert assess_property_page(200, "Normale Immobilienanzeige") == ("live", "http_live")
    assert assess_property_page(403, "Access blocked") == ("unknown", "http_403")
    assert assess_property_page(200, "Just a moment") == (
        "unknown",
        "cloudflare_challenge",
    )


def test_property_liveness_is_rechecked_daily() -> None:
    assert PROPERTY_LIVENESS_RECHECK_HOURS == 24


def test_transient_unknown_does_not_hide_previously_proven_live_listing() -> None:
    listing = PropertyListing(
        raw_payload={
            "source_price_eur": "150000",
            "source_liveness_required": True,
            "source_liveness_state": "live",
            "source_liveness_last_live_at": "2026-08-29T01:00:00+00:00",
            "product_visible": True,
            "product_visibility_reason": "accepted",
        }
    )

    _apply_persisted_probe(
        listing,
        PropertyLivenessProbe(
            state="unknown",
            status_code=429,
            reason="http_429",
            final_url="https://portal.example/expose/1",
        ),
    )

    assert listing.raw_payload["source_liveness_state"] == "unknown"
    assert listing.raw_payload["product_visible"] is True
    assert listing.raw_payload["product_visibility_reason"] == "accepted"


def test_definitive_dead_still_hides_previously_live_listing() -> None:
    listing = PropertyListing(
        raw_payload={
            "source_price_eur": "150000",
            "source_liveness_required": True,
            "source_liveness_state": "live",
            "source_liveness_last_live_at": "2026-08-29T01:00:00+00:00",
            "product_visible": True,
            "product_visibility_reason": "accepted",
        }
    )

    _apply_persisted_probe(
        listing,
        PropertyLivenessProbe(
            state="dead",
            status_code=404,
            reason="http_404",
            final_url="https://portal.example/expose/1",
        ),
    )

    assert listing.raw_payload["product_visible"] is False
    assert listing.raw_payload["product_visibility_reason"] == "source_dead"
