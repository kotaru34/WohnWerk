from app import product_ui_middleware as product_ui


def _rendered_live_script() -> str:
    return product_ui._inject_product_chrome(
        b"<html><body><main><div>catalog</div></main></body></html>",
        notice=None,
        live_cursor=27,
    ).decode()


def test_live_sync_is_injected_outside_replaceable_main() -> None:
    rendered = _rendered_live_script()

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


def test_live_client_intercepts_catalog_curation_without_navigation() -> None:
    rendered = _rendered_live_script()

    assert 'document.addEventListener("submit"' in rendered
    assert 'event.preventDefault();' in rendered
    assert 'new FormData(form)' in rendered
    assert 'method: "POST"' in rendered
    assert 'redirect: "follow"' in rendered
    assert 'X-WohnWerk-Async' in rendered
    assert 'form.dataset.wwPending' in rendered


def test_live_refresh_restores_viewport_after_main_replacement() -> None:
    rendered = _rendered_live_script()

    assert 'const snapshot = viewportSnapshot();' in rendered
    assert 'currentMain.replaceWith(nextMain);' in rendered
    assert 'restoreViewport(snapshot);' in rendered
    assert 'window.scrollBy(0, delta);' in rendered
    assert 'window.scrollTo(0, Math.min(snapshot.scrollY, maximum));' in rendered


def test_house_detail_hide_keeps_navigation_fallback() -> None:
    rendered = _rendered_live_script()

    assert '/^\\/houses\\/\\d+$/.test(window.location.pathname)' in rendered
    assert '/\\/hidden$/.test(action)' in rendered
