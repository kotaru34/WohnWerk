from decimal import Decimal

from app.matches import PropertyMatchView, PropertySourceLink
from app.matching import PropertyDistanceMatch


def _spatial(*, living: Decimal | None, plot: Decimal | None) -> PropertyDistanceMatch:
    return PropertyDistanceMatch(
        property_id=1,
        title="Testhaus",
        postal_code="1010",
        city="Wien",
        price_eur=Decimal(500000),
        living_area_m2=living,
        plot_area_m2=plot,
        job_location_id=1,
        job_postal_code="1010",
        job_city="Wien",
        job_location_text="Wien",
        distance_km=1.0,
    )


def test_verified_living_area_hides_neutral_display_area() -> None:
    view = PropertyMatchView(
        spatial=_spatial(living=Decimal(145), plot=Decimal(800)),
        road_distance_km=None,
        road_duration_minutes=None,
        links=(
            PropertySourceLink(
                label="immmo.at",
                url="https://example.test/house",
                display_area_m2=Decimal(145),
            ),
        ),
    )

    assert view.neutral_area_m2 is None
    assert view.visible_plot_area_m2 == Decimal(800)


def test_unverified_display_area_is_exposed_neutrally() -> None:
    view = PropertyMatchView(
        spatial=_spatial(living=None, plot=Decimal(800)),
        road_distance_km=None,
        road_duration_minutes=None,
        links=(
            PropertySourceLink(
                label="immmo.at",
                url="https://example.test/house",
                display_area_m2=Decimal("188.51"),
            ),
        ),
    )

    assert view.neutral_area_m2 == Decimal("188.51")
    assert view.visible_plot_area_m2 == Decimal(800)


def test_ambiguous_equal_plot_is_not_relabelled_as_ground() -> None:
    view = PropertyMatchView(
        spatial=_spatial(living=None, plot=Decimal(5256)),
        road_distance_km=None,
        road_duration_minutes=None,
        links=(
            PropertySourceLink(
                label="immmo.at",
                url="https://example.test/house",
                display_area_m2=Decimal(5256),
            ),
        ),
    )

    assert view.neutral_area_m2 == Decimal(5256)
    assert view.visible_plot_area_m2 is None


def test_conflicting_display_areas_fail_closed() -> None:
    view = PropertyMatchView(
        spatial=_spatial(living=None, plot=None),
        road_distance_km=None,
        road_duration_minutes=None,
        links=(
            PropertySourceLink(
                label="immmo.at",
                url="https://example.test/a",
                display_area_m2=Decimal(120),
            ),
            PropertySourceLink(
                label="immmo.at",
                url="https://example.test/b",
                display_area_m2=Decimal(784),
            ),
        ),
    )

    assert view.neutral_area_m2 is None
