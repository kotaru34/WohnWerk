from decimal import Decimal

from sqlalchemy.dialects import postgresql

from app.catalog import (
    PropertySourceView,
    PropertyView,
    _properties_within_radius_for_job_stmt,
)
from app.house_filters import HouseFilters
from app.models import Property


def test_property_view_prefers_source_backed_image_and_neutral_area() -> None:
    property_row = Property(
        id=7,
        title="Haus",
        living_area_m2=None,
        plot_area_m2=Decimal(800),
    )
    view = PropertyView(
        property=property_row,
        sources=(
            PropertySourceView(
                label="immmo.at",
                url="https://example.test/house",
                display_area_m2=Decimal("188.51"),
                primary_image_url="https://images.example.test/house.jpg",
            ),
        ),
    )

    assert view.image_url == "https://images.example.test/house.jpg"
    assert view.neutral_area_m2 == Decimal("188.51")
    assert view.visible_plot_area_m2 == Decimal(800)


def test_property_view_hides_ambiguous_duplicate_plot_label() -> None:
    property_row = Property(
        id=8,
        title="Grundstück",
        living_area_m2=None,
        plot_area_m2=Decimal(748),
    )
    view = PropertyView(
        property=property_row,
        sources=(
            PropertySourceView(
                label="immmo.at",
                url="https://example.test/plot",
                display_area_m2=Decimal(748),
            ),
        ),
    )

    assert view.neutral_area_m2 == Decimal(748)
    assert view.visible_plot_area_m2 is None


def test_job_house_radius_query_is_indexable_postgis_query() -> None:
    stmt = _properties_within_radius_for_job_stmt(144, 50.0)
    sql = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "ST_DWithin" in sql
    assert "ST_Distance" in sql
    assert "row_number() OVER" in sql
    assert "properties.status = 'active'" in sql
    assert "job_locations.job_id = 144" in sql


def test_job_house_radius_query_applies_saved_house_filters() -> None:
    stmt = _properties_within_radius_for_job_stmt(
        144,
        50.0,
        HouseFilters(
            preis_von=Decimal(30000),
            preis_bis=Decimal(150000),
            wohn_von=Decimal(90),
            grund_von=Decimal(300),
        ),
    )
    sql = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "properties.price_eur >= 30000" in sql
    assert "properties.price_eur <= 150000" in sql
    assert "properties.living_area_m2 >= 90" in sql
    assert "properties.plot_area_m2 >= 300" in sql
