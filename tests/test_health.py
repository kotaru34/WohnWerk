from fastapi.testclient import TestClient

from app.jobs.concept_catalog import EXTRACTOR_VERSION
from app.main import app
from app.version import __version__

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "wohnwerk"
    assert payload["version"] == __version__
    assert payload["job_concept_extractor"] == EXTRACTOR_VERSION
    assert payload["country"] == "DE"


def test_health_describes_air_only_mode_when_graph_has_not_been_confirmed(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from app import main

    monkeypatch.setattr(main, "settings", SimpleNamespace(
        country_code="DE",
        ai_enabled=False,
        routing_enabled=True,
        routing_graph_countries="",
        workplace_geocoding_enabled=False,
    ))
    result = main.health()
    assert result["road_routing_mode"] == "air_distance_only"
    assert result["workplace_geocoding_enabled"] is False


def test_health_declares_osrm_mode_without_claiming_live_validation(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    from app import main

    monkeypatch.setattr(main, "settings", SimpleNamespace(
        country_code="DE",
        ai_enabled=False,
        routing_enabled=True,
        routing_graph_countries="DE",
        workplace_geocoding_enabled=True,
    ))
    result = main.health()
    assert result["road_routing_mode"] == "de_graph_declared"
    assert result["workplace_geocoding_enabled"] is True
