from app.product_ui_middleware import _inject_product_chrome
from app.version import __version__


def test_brand_injection_shows_project_name_and_version() -> None:
    rendered = _inject_product_chrome(
        b"<html><body><main><nav class=\"topnav\"></nav></main></body></html>",
        notice=None,
    ).decode()

    assert "ww-product-brand" in rendered
    assert ">WohnWerk<" in rendered
    assert f"v{__version__}" in rendered


def test_geo_notice_is_inserted_after_job_header() -> None:
    rendered = _inject_product_chrome(
        b'<html><body><main><section class="job-head">job</section><div>houses</div></main></body></html>',
        notice="Die Geoposition ist nur angenähert.",
    ).decode()

    assert "Standort nur eingeschränkt genau" in rendered
    assert "Die Geoposition ist nur angenähert." in rendered
    assert rendered.index('<aside class="ww-geo-warning"') > rendered.index("job-head")
