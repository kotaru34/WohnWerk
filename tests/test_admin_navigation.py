from pathlib import Path


TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"


def test_concepts_page_uses_same_primary_admin_navigation_as_health() -> None:
    concepts = (TEMPLATES / "admin_concepts.html").read_text(encoding="utf-8")
    health = (TEMPLATES / "admin_health.html").read_text(encoding="utf-8")

    expected_links = (
        '<a href="/houses">Häuser</a>',
        '<a href="/jobs">Stellen</a>',
        '<a href="/admin/concepts" class="active">Konzepte</a>',
        '<a href="/admin/health">Betrieb</a>',
    )
    for link in expected_links:
        assert link in concepts

    assert '<a href="/admin/jobs">Stellen</a>' not in concepts
    assert "flex-wrap: wrap" in concepts
    assert "h1 { margin: 0 0 4px; }" in concepts
    assert '<a href="/houses">Häuser</a>' in health
    assert '<a href="/jobs">Stellen</a>' in health
