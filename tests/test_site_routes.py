from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.admin import require_admin, require_csrf
from app.database import get_db
from app.jobs.candidate_fit import CandidateProfile
from app.jobs.candidate_profile_seed import PROFILE_SLUG
from app.main import app


def _session_with_profile() -> tuple[object, Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    CandidateProfile.__table__.create(engine)
    session = Session(engine)
    session.add(
        CandidateProfile(
            slug=PROFILE_SLUG,
            label_de="Maschinenbau / technische Projektleitung",
            enabled=True,
        )
    )
    session.commit()
    return engine, session


def test_root_and_father_facing_routes_are_registered() -> None:
    with TestClient(app) as client:
        root = client.get("/", follow_redirects=False)

    assert root.status_code == 307
    assert root.headers["location"] == "/matches"

    paths = {route.path for route in app.routes}
    assert "/matches" in paths
    assert "/jobs" in paths
    assert "/jobs/{job_id}/favorite" in paths
    assert "/jobs/{job_id}/hidden" in paths
    assert "/admin/concepts" in paths


def test_father_facing_job_curation_redirects_back_to_jobs(monkeypatch) -> None:
    engine, session = _session_with_profile()
    calls: list[tuple[str, int, bool]] = []

    def override_db():
        yield session

    monkeypatch.setattr(
        "app.site.set_job_favorite",
        lambda _db, _profile, job_id, *, favorite: calls.append(("favorite", job_id, favorite)),
    )
    monkeypatch.setattr(
        "app.site.set_job_hidden",
        lambda _db, _profile, job_id, *, hidden: calls.append(("hidden", job_id, hidden)),
    )
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[require_csrf] = lambda: None
    try:
        with TestClient(app) as client:
            favorite = client.post(
                "/jobs/144/favorite",
                data={"favorite": "1", "return_view": "alle", "return_search": "Graz"},
                follow_redirects=False,
            )
            assert favorite.status_code == 303
            assert favorite.headers["location"] == "/jobs?ansicht=alle&suche=Graz#job-144"

            hidden = client.post(
                "/jobs/144/hidden",
                data={"hidden": "1", "return_view": "passend"},
                follow_redirects=False,
            )
            assert hidden.status_code == 303
            assert hidden.headers["location"] == "/jobs?ansicht=passend#job-144"

        assert calls == [("favorite", 144, True), ("hidden", 144, True)]
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
