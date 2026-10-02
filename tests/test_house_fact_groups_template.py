from pathlib import Path

from app.templates_runtime import templates


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "app" / "templates"


def test_house_templates_compile_with_shared_semantic_fact_groups() -> None:
    for name in ("houses.html", "house_detail.html", "_house_fact_groups.html"):
        templates.env.get_template(name)

    partial = (TEMPLATE_DIR / "_house_fact_groups.html").read_text(encoding="utf-8")
    labels = ("Objekt", "Heizung", "Distanzen", "Internet")
    positions = [partial.index(f"<span>{label}</span>") for label in labels]

    assert positions == sorted(positions)
    assert partial.count("<svg") == 4
    assert "fact-chip good" in partial
    assert "fact-chip warn" in partial
    assert "fact-chip muted" in partial

    for name in ("houses.html", "house_detail.html"):
        source = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
        assert '{% include "_house_fact_groups.html" %}' in source
        assert "fact-group-label" in source
