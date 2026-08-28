from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.admin import require_admin
from app.database import get_db
from app.jobs.candidate_fit import (
    CandidatePreferenceState,
    CandidateProfile,
    FitHardConstraint,
    JobFitResult,
)
from app.jobs.candidate_profile_seed import PROFILE_SLUG
from app.jobs.concepts import ConceptKind
from app.jobs.fit_store import JobFitDriverView, JobFitView, JobSourceLink
from app.main import app
from app.models import Job


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


def _result(score: int | None, *, hard: bool = False, coverage: float = 0.6) -> JobFitResult:
    constraints = (
        (
            FitHardConstraint(
                kind=ConceptKind.DOMAIN,
                slug="electronics",
                state=CandidatePreferenceState.CANNOT_NOT_WANT,
            ),
        )
        if hard
        else ()
    )
    return JobFitResult(
        score=score,
        signed_score=None if score is None else (score - 50) / 50,
        rated_weight=0.0 if score is None else 2.0,
        total_weight=3.0,
        preference_coverage=coverage,
        contributions=(),
        hard_constraints=constraints,
    )


def _views() -> list[JobFitView]:
    mechanical = Job(id=144, title="Mechanical Design Engineer", company="eXperts")
    electrical = Job(id=259, title="Elektronik-Entwicklungsingenieur", company="BORA")
    unrated = Job(id=999, title="Unklare technische Stelle", company="Beispiel GmbH")
    return [
        JobFitView(
            job=mechanical,
            result=_result(100, coverage=0.638),
            locations=("8010 Graz",),
            links=(JobSourceLink(label="karriere.at", url="https://example.test/144"),),
            drivers=(JobFitDriverView(label_de="Maschinenbau", contribution=1.25),),
            hard_labels=(),
        ),
        JobFitView(
            job=electrical,
            result=_result(25, hard=True, coverage=1.0),
            locations=("Wien",),
            links=(),
            drivers=(JobFitDriverView(label_de="Elektronik / Hardware", contribution=-1.25),),
            hard_labels=("Elektronik / Hardware",),
        ),
        JobFitView(
            job=unrated,
            result=_result(None, coverage=0.0),
            locations=("Linz",),
            links=(),
            drivers=(),
            hard_labels=(),
        ),
    ]


def test_admin_jobs_live_ranking_filters(monkeypatch) -> None:
    engine, session = _session_with_profile()

    def override_db():
        yield session

    monkeypatch.setattr("app.admin.load_live_job_fit", lambda *_args, **_kwargs: _views())
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    try:
        with TestClient(app) as client:
            page = client.get("/admin/jobs")
            assert page.status_code == 200
            assert "Stellenranking" in page.text
            assert "Mechanical Design Engineer" in page.text
            assert "Elektronik-Entwicklungsingenieur" not in page.text
            assert "Unklare technische Stelle" not in page.text
            assert "100" in page.text
            assert "Maschinenbau" in page.text
            assert "8010 Graz" in page.text

            hard = client.get("/admin/jobs?ansicht=unvereinbar")
            assert hard.status_code == 200
            assert "Elektronik-Entwicklungsingenieur" in hard.text
            assert "Unvereinbar: Elektronik / Hardware" in hard.text
            assert "Mechanical Design Engineer" not in hard.text

            unrated = client.get("/admin/jobs?ansicht=unbewertet")
            assert unrated.status_code == 200
            assert "Unklare technische Stelle" in unrated.text
            assert "Mechanical Design Engineer" not in unrated.text

            search = client.get("/admin/jobs?ansicht=alle&suche=graz")
            assert search.status_code == 200
            assert "Mechanical Design Engineer" in search.text
            assert "Elektronik-Entwicklungsingenieur" not in search.text
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
