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
    assert payload["country"] == "AT"
