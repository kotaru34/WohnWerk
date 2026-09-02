from app import product_ui_middleware as product_ui
from app.version import __version__


def test_brand_injection_shows_project_name_and_version() -> None:
    rendered = product_ui._inject_product_chrome(
        b"<html><body><main><nav class=\"topnav\"></nav></main></body></html>",
        notice=None,
    ).decode()

    assert "ww-product-brand" in rendered
    assert ">WohnWerk<" in rendered
    assert f"v{__version__}" in rendered


def test_geo_notice_is_inserted_after_job_header() -> None:
    rendered = product_ui._inject_product_chrome(
        b'<html><body><main><section class="job-head">job</section><div>houses</div></main></body></html>',
        notice="Die Geoposition ist nur angenähert.",
    ).decode()

    assert "Standort nur eingeschränkt genau" in rendered
    assert "Die Geoposition ist nur angenähert." in rendered
    assert rendered.index('<aside class="ww-geo-warning"') > rendered.index("job-head")


def test_bundesland_only_labels_are_recognized_as_intentionally_broad() -> None:
    assert product_ui._BROAD_REGION_ONLY_RE.match("Kärnten, Österreich")
    assert product_ui._BROAD_REGION_ONLY_RE.match("Oberösterreich")
    assert product_ui._BROAD_REGION_ONLY_RE.match("Austria")
    assert not product_ui._BROAD_REGION_ONLY_RE.match("Salzburg Umgebung")
    assert not product_ui._BROAD_REGION_ONLY_RE.match("Oberösterreich Zentralraum")
