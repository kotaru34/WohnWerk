from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.admin import require_admin
from app.database import get_db
from app.jobs.candidate_fit import CandidateProfile, JobFitResult
from app.jobs.candidate_profile_seed import PROFILE_SLUG
from app.jobs.fit_store import JobFitView, JobSourceLink
from app.main import app
from app.matches import JobMatchView, PropertyMatchView, PropertySourceLink
from app.matching import PropertyDistanceMatch
from app.models import Job
from app.routing import RoutingError


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


def _group(*, road: bool) -> JobMatchView:
    fit = JobFitView(
        job=Job(id=205, title="Senior Konstrukteur Maschinenbau", company="Beispiel GmbH"),
        result=JobFitResult(
            score=94,
            signed_score=0.88,
            rated_weight=3.0,
            total_weight=3.0,
            preference_coverage=1.0,
            contributions=(),
            hard_constraints=(),
        ),
        locations=("4600 Wels",),
        links=(JobSourceLink(label="jobs.at", url="https://example.test/job"),),
        drivers=(),
        hard_labels=(),
    )
    spatial = PropertyDistanceMatch(
        property_id=7001,
        title="Haus im Grünen",
        postal_code="4614",
        city="Marchtrenk",
        price_eur=Decimal("499000"),
        living_area_m2=Decimal("145"),
        plot_area_m2=Decimal("800"),
        job_location_id=12,
        job_postal_code="4600",
        job_city="Wels",
        job_location_text="Wels",
        distance_km=8.2,
    )
    return JobMatchView(
        fit=fit,
        properties=(
            PropertyMatchView(
                spatial=spatial,
                road_distance_km=12.4 if road else None,
                road_duration_minutes=14.2 if road else None,
            ),
        ),
    )


def _override_links(*_args, **_kwargs):
    return {
        7001: (
            PropertySourceLink(label="immmo.at", url="https://example.test/house"),
        )
    }


def test_matches_page_renders_road_commute_and_live_sources(monkeypatch) -> None:
    engine, session = _session_with_profile()

    def override_db():
        yield session

    monkeypatch.setattr(
        "app.matches.get_settings",
        lambda: SimpleNamespace(routing_enabled=True),
    )
    monkeypatch.setattr("app.matches._road_groups", lambda *_args, **_kwargs: [_group(road=True)])
    monkeypatch.setattr("app.matches._property_links", _override_links)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    try:
        with TestClient(app) as client:
            page = client.get("/admin/matches")
            assert page.status_code == 200
            assert "Stellen & passende Häuser" in page.text
            assert "live aus der aktuellen WohnWerk-Datenbank" in page.text
            assert "Senior Konstrukteur Maschinenbau" in page.text
            assert "Haus im Grünen" in page.text
            assert "14 min" in page.text
            assert "12.4 km Straße" in page.text
            assert "8.2 km" in page.text
            assert "jobs.at" in page.text
            assert "immmo.at" in page.text
            assert "Straßenberechnung ist" not in page.text
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_matches_page_falls_back_to_air_distance_when_router_fails(monkeypatch) -> None:
    engine, session = _session_with_profile()

    def override_db():
        yield session

    def fail_road(*_args, **_kwargs):
        raise RoutingError("router unavailable")

    monkeypatch.setattr(
        "app.matches.get_settings",
        lambda: SimpleNamespace(routing_enabled=True),
    )
    monkeypatch.setattr("app.matches._road_groups", fail_road)
    monkeypatch.setattr("app.matches._air_groups", lambda *_args, **_kwargs: [_group(road=False)])
    monkeypatch.setattr("app.matches._property_links", _override_links)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: None
    try:
        with TestClient(app) as client:
            page = client.get("/admin/matches")
            assert page.status_code == 200
            assert "vorübergehend nicht erreichbar" in page.text
            assert "Luftlinie" in page.text
            assert "8.2 km" in page.text
            assert "12.4 km Straße" not in page.text
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
