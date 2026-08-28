from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.admin import require_admin
from app.database import get_db
from app.main import app


def test_admin_concept_rating_filter_highlights_remaining_work(monkeypatch) -> None:
    rated = SimpleNamespace(
        concept=SimpleNamespace(
            id=1,
            kind="domain",
            slug="mechanical-engineering",
            label_de="Maschinenbau",
            enabled=True,
            aliases=[],
        ),
        preference=SimpleNamespace(state="can_want", source="manual", seed_version=None),
        evidence_jobs=12,
        evidence_primary=5,
        evidence_context=10,
    )
    unrated = SimpleNamespace(
        concept=SimpleNamespace(
            id=2,
            kind="domain",
            slug="new-domain",
            label_de="Noch offenes Fachgebiet",
            enabled=True,
            aliases=[],
        ),
        preference=None,
        evidence_jobs=3,
        evidence_primary=1,
        evidence_context=2,
    )

    def override_db():
        yield object()

    monkeypatch.setattr(
        "app.admin.get_settings",
        lambda: SimpleNamespace(admin_username="admin", admin_password="test"),
    )
    monkeypatch.setattr(
        "app.admin._profile_or_503",
        lambda _db: SimpleNamespace(label_de="Testprofil"),
    )
    monkeypatch.setattr(
        "app.admin.list_concepts_for_admin",
        lambda *_args, **_kwargs: [rated, unrated],
    )
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    try:
        with TestClient(app) as client:
            page = client.get("/admin/concepts?bewertung=unbewertet")
            assert page.status_code == 200
            assert "Noch offenes Fachgebiet" in page.text
            assert "Maschinenbau" not in page.text
            assert "1 bewertet" in page.text
            assert "1 noch unbewertet" in page.text
            assert 'class="concept unrated"' in page.text

            rated_page = client.get("/admin/concepts?bewertung=bewertet")
            assert rated_page.status_code == 200
            assert "Maschinenbau" in rated_page.text
            assert "Noch offenes Fachgebiet" not in rated_page.text
            assert 'class="concept rated"' in rated_page.text
    finally:
        app.dependency_overrides.clear()
