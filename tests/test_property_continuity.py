from decimal import Decimal

from app.ingestion.property_continuity import (
    PropertyContinuityObservation,
    continuity_area_m2,
    match_property_continuity,
)


def observation(
    token: str,
    *,
    title: str = "Idyllisches Einfamilienhaus auf ebenem Grund am Waldrand",
    postal_code: str = "3002",
    price: str | None = "395000",
    area: str | None = "100",
) -> PropertyContinuityObservation:
    return PropertyContinuityObservation(
        token=token,
        postal_code=postal_code,
        title=title,
        price_eur=Decimal(price) if price is not None else None,
        living_area_m2=Decimal(area) if area is not None else None,
    )


def test_continuity_prefers_raw_display_area_over_semantic_living_area() -> None:
    assert continuity_area_m2(
        {"display_area_m2": "748"},
        Decimal("130"),
    ) == Decimal("748")


def test_continuity_legacy_rows_fall_back_to_historical_living_area() -> None:
    assert continuity_area_m2({}, Decimal("212.02")) == Decimal("212.02")


def test_exact_metadata_reconnects_rotated_provider_identity() -> None:
    matches = match_property_continuity(
        [observation("old")],
        [observation("new")],
    )

    assert len(matches) == 1
    assert matches[0].previous_token == "old"
    assert matches[0].current_token == "new"
    assert matches[0].strategy == "exact"


def test_price_change_falls_back_to_unique_title_and_area() -> None:
    matches = match_property_continuity(
        [observation("old", price="395000")],
        [observation("new", price="379000")],
    )

    assert len(matches) == 1
    assert matches[0].strategy == "title_area"


def test_area_change_with_same_price_fails_closed() -> None:
    matches = match_property_continuity(
        [observation("old", area="100")],
        [observation("new", area="104")],
    )

    assert matches == []


def test_large_provider_area_semantic_change_fails_closed() -> None:
    matches = match_property_continuity(
        [observation("old", price="41000", area="212.02")],
        [observation("new", price="41000", area="7246.04")],
    )

    assert matches == []


def test_price_and_area_change_fail_closed() -> None:
    matches = match_property_continuity(
        [observation("old", price="395000", area="100")],
        [observation("new", price="379000", area="104")],
    )

    assert matches == []


def test_ambiguous_development_rows_fail_closed() -> None:
    previous = [
        observation("old-a", title="Modernes Reihenhaus im Wohnpark Musterfeld"),
        observation("old-b", title="Modernes Reihenhaus im Wohnpark Musterfeld"),
    ]
    current = [
        observation("new-a", title="Modernes Reihenhaus im Wohnpark Musterfeld"),
        observation("new-b", title="Modernes Reihenhaus im Wohnpark Musterfeld"),
    ]

    assert match_property_continuity(previous, current) == []
