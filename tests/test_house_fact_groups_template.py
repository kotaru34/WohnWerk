from app.templates_runtime import templates


def _source(name: str) -> str:
    source, _filename, _uptodate = templates.env.loader.get_source(templates.env, name)
    return source


def test_house_templates_compile_with_shared_semantic_fact_groups() -> None:
    for name in ("houses.html", "house_detail.html", "_house_fact_groups.html"):
        templates.env.get_template(name)

    partial = _source("_house_fact_groups.html")
    labels = ("Objekt", "Heizung", "Distanzen", "Internet")
    positions = [partial.index(f"<span>{label}</span>") for label in labels]

    assert positions == sorted(positions)
    assert partial.count("<svg") == 4
    assert "fact-chip good" in partial
    assert "fact-chip warn" in partial
    assert "fact-chip muted" in partial

    for name in ("houses.html", "house_detail.html"):
        source = _source(name)
        assert '{% include "_house_fact_groups.html" %}' in source
        assert "fact-group-label" in source
