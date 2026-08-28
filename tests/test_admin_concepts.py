import re
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.admin import require_admin
from app.database import get_db
from app.jobs.candidate_fit import (
    CandidateConceptPreference,
    CandidatePreferenceSource,
    CandidatePreferenceState,
    CandidateProfile,
)
from app.jobs.candidate_profile_seed import PROFILE_SEED_VERSION, PROFILE_SLUG
from app.jobs.concepts import JobConcept, JobConceptAlias, JobConceptEvidence
from app.main import app
from app.models import Job


def _database() -> tuple[object, Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Job.__table__.create(engine)
    JobConcept.__table__.create(engine)
    JobConceptAlias.__table__.create(engine)
    JobConceptEvidence.__table__.create(engine)
    CandidateProfile.__table__.create(engine)
    CandidateConceptPreference.__table__.create(engine)
    return engine, Session(engine)


def _seed_profile_and_concept(session: Session) -> tuple[CandidateProfile, JobConcept]:
    concept = JobConcept(
        kind="domain",
        slug="mechanical-engineering",
        label_de="Maschinenbau",
        enabled=True,
    )
    profile = CandidateProfile(
        slug=PROFILE_SLUG,
        label_de="Maschinenbau / technische Projektleitung",
        enabled=True,
    )
    session.add_all([concept, profile])
    session.flush()
    session.add(
        CandidateConceptPreference(
            profile_id=profile.id,
            concept_id=concept.id,
            state=CandidatePreferenceState.CAN_WANT.value,
            source=CandidatePreferenceSource.SEED.value,
            seed_version=PROFILE_SEED_VERSION,
        )
    )
    session.commit()
    return profile, concept


def test_admin_is_fail_closed_without_password(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.admin.get_settings",
        lambda: SimpleNamespace(admin_username="admin", admin_password=None),
    )
    with TestClient(app) as client:
        response = client.get("/admin/concepts")
    assert response.status_code == 503


def test_admin_preference_and_alias_lifecycle(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.admin.get_settings",
        lambda: SimpleNamespace(admin_username="admin", admin_password="test-passwort-ä"),
    )
    engine, session = _database()
    profile, concept = _seed_profile_and_concept(session)

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    try:
        with TestClient(app) as client:
            page = client.get("/admin/concepts?kind=domain")
            assert page.status_code == 200
            assert "Kandidatenprofil" in page.text
            assert "Fachgebiet" in page.text
            assert "Maschinenbau" in page.text
            assert "Kann ich / möchte ich" in page.text
            match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
            assert match is not None
            csrf_token = match.group(1)

            changed = client.post(
                f"/admin/concepts/{concept.id}/preference",
                data={
                    "csrf_token": csrf_token,
                    "state": "cannot_not_want",
                    "return_kind": "domain",
                },
                follow_redirects=False,
            )
            assert changed.status_code == 303

            preference = session.scalar(
                select(CandidateConceptPreference).where(
                    CandidateConceptPreference.profile_id == profile.id,
                    CandidateConceptPreference.concept_id == concept.id,
                )
            )
            assert preference is not None
            assert preference.state == CandidatePreferenceState.CANNOT_NOT_WANT.value
            assert preference.source == CandidatePreferenceSource.MANUAL.value
            assert preference.seed_version is None

            reset = client.post(
                f"/admin/concepts/{concept.id}/preference/reset",
                data={"csrf_token": csrf_token, "return_kind": "domain"},
                follow_redirects=False,
            )
            assert reset.status_code == 303
            session.refresh(preference)
            assert preference.state == CandidatePreferenceState.CAN_WANT.value
            assert preference.source == CandidatePreferenceSource.SEED.value
            assert preference.seed_version == PROFILE_SEED_VERSION

            added = client.post(
                f"/admin/concepts/{concept.id}/aliases",
                data={
                    "csrf_token": csrf_token,
                    "alias": "Maschinenbau-Fachgebiet",
                    "language": "de",
                },
                follow_redirects=False,
            )
            assert added.status_code == 303
            alias = session.scalar(
                select(JobConceptAlias).where(JobConceptAlias.concept_id == concept.id)
            )
            assert alias is not None
            assert alias.alias == "Maschinenbau-Fachgebiet"
            assert alias.source == "manual"
            assert alias.enabled is True

            toggled = client.post(
                f"/admin/aliases/{alias.id}/toggle",
                data={"csrf_token": csrf_token, "concept_id": concept.id, "enabled": "0"},
                follow_redirects=False,
            )
            assert toggled.status_code == 303
            session.refresh(alias)
            assert alias.enabled is False

            removed = client.post(
                f"/admin/aliases/{alias.id}/delete",
                data={"csrf_token": csrf_token, "concept_id": concept.id},
                follow_redirects=False,
            )
            assert removed.status_code == 303
            assert session.get(JobConceptAlias, alias.id) is None
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
