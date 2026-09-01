from app import product_ui_middleware as product_ui


def test_live_sync_is_injected_outside_replaceable_main() -> None:
    rendered = product_ui._inject_product_chrome(
        b"<html><body><main><div>catalog</div></main></body></html>",
        notice=None,
        live_cursor=27,
    ).decode()

    assert 'id="wohnwerk-live-sync"' in rendered
    assert "/events?after=${initialCursor}" in rendered
    assert "const initialCursor = 27;" in rendered
    assert rendered.index("</main>") < rendered.index('id="wohnwerk-live-sync"')


def test_live_sync_is_not_injected_without_cursor() -> None:
    rendered = product_ui._inject_product_chrome(
        b"<html><body><main><div>catalog</div></main></body></html>",
        notice=None,
    ).decode()

    assert 'id="wohnwerk-live-sync"' not in rendered


def test_only_product_gets_are_live_enabled() -> None:
    assert product_ui._live_product_path("/houses", "GET")
    assert product_ui._live_product_path("/houses/42", "GET")
    assert product_ui._live_product_path("/jobs", "GET")
    assert product_ui._live_product_path("/jobs/7", "GET")
    assert not product_ui._live_product_path("/jobs/7/favorite", "POST")
    assert not product_ui._live_product_path("/admin/health", "GET")
