import importlib.util
import sys
from pathlib import Path

from app.refresh import DueSourceRun, SourceRefreshPlan

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "refresh_sources.py"
SPEC = importlib.util.spec_from_file_location("wohnwerk_refresh_sources_script", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
_runtime_release_gate = MODULE._runtime_release_gate
_source_command = MODULE._source_command


class _HealthResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


def _run(source_name: str, *, reconciliation: bool) -> DueSourceRun:
    return DueSourceRun(
        plan=SourceRefreshPlan(
            source_name=source_name,
            script=f"scripts/run_{source_name.replace('.', '_')}.py",
            supports_reconciliation=True,
        ),
        reconciliation=reconciliation,
    )


def _health_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "ok",
        "service": "wohnwerk",
        "version": MODULE.__version__,
        "job_concept_extractor": MODULE.EXTRACTOR_VERSION,
    }
    payload.update(overrides)
    return payload


def test_sreal_detail_enrichment_only_runs_on_reconciliation() -> None:
    full = _source_command(_run("sreal.at", reconciliation=True))
    incremental = _source_command(_run("sreal.at", reconciliation=False))

    assert "--reconcile" in full
    assert "--enrich-details" in full
    assert "--reconcile" not in incremental
    assert "--enrich-details" not in incremental


def test_other_reconciliation_sources_do_not_get_sreal_flag() -> None:
    command = _source_command(_run("immmo.at", reconciliation=True))

    assert "--reconcile" in command
    assert "--enrich-details" not in command


def test_runtime_release_gate_accepts_matching_web_reader(monkeypatch) -> None:
    monkeypatch.setattr(
        MODULE.httpx,
        "get",
        lambda *_args, **_kwargs: _HealthResponse(_health_payload()),
    )

    accepted, reason = _runtime_release_gate("http://example.test/health")

    assert accepted is True
    assert reason == "ok"


def test_runtime_release_gate_defers_on_web_version_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(
        MODULE.httpx,
        "get",
        lambda *_args, **_kwargs: _HealthResponse(_health_payload(version="older-release")),
    )

    accepted, reason = _runtime_release_gate("http://example.test/health")

    assert accepted is False
    assert reason == "web_version_mismatch"


def test_runtime_release_gate_defers_when_web_lacks_extractor_marker(monkeypatch) -> None:
    payload = _health_payload()
    payload.pop("job_concept_extractor")
    monkeypatch.setattr(
        MODULE.httpx,
        "get",
        lambda *_args, **_kwargs: _HealthResponse(payload),
    )

    accepted, reason = _runtime_release_gate("http://example.test/health")

    assert accepted is False
    assert reason == "web_extractor_mismatch"


def test_runtime_release_gate_defers_on_non_object_health_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        MODULE.httpx,
        "get",
        lambda *_args, **_kwargs: _HealthResponse(["ok"]),
    )

    accepted, reason = _runtime_release_gate("http://example.test/health")

    assert accepted is False
    assert reason == "invalid_web_health"
