from app.templates_runtime import templates


def _source(name: str) -> str:
    source, _filename, _uptodate = templates.env.loader.get_source(templates.env, name)
    return source


def test_house_source_badge_partial_compiles_and_links_to_provenance() -> None:
    templates.env.get_template("_house_source_badges.html")
    source = _source("_house_source_badges.html")

    assert "source.brand.color" in source
    assert "source.brand.icon_text" in source
    assert "source.brand.label" in source
    assert 'href="{{ source.url }}"' in source
    assert 'rel="noopener noreferrer"' in source


def test_source_badges_render_before_seen_state_on_card_and_detail() -> None:
    for name in ("houses.html", "house_detail.html"):
        templates.env.get_template(name)
        source = _source(name)
        include_at = source.index('{% include "_house_source_badges.html" %}')
        seen_at = source.index("Gesehen", include_at)
        assert include_at < seen_at
        assert ".source-badge" in source
        assert ".source-icon" in source
