import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import SourceCategory
from app.refresh import DueSourceRun, SourceRefreshPlan

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "refresh_sources.py"
_SPEC = importlib.util.spec_from_file_location("wohnwerk_test_refresh_sources", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
refresh_sources = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = refresh_sources
_SPEC.loader.exec_module(refresh_sources)


class _SessionContext:
    def __enter__(self):
        return object()

    def __exit__(self, *_args):
        return False


class _Lock:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _configure_main(monkeypatch, *, postprocess_failure: str | None):
    run = DueSourceRun(
        plan=SourceRefreshPlan("example-jobs", "scripts/run_example.py", False),
        reconciliation=False,
    )
    lock = _Lock()
    calls: list[str] = []
    published: list[list[str]] = []

    monkeypatch.setattr(
        refresh_sources,
        "parse_args",
        lambda: SimpleNamespace(
            lock_path=None,
            reconciliation_retry_minutes=180,
            health_url="http://test/health",
            dry_run=False,
        ),
    )
    monkeypatch.setattr(refresh_sources, "_acquire_lock", lambda _path: lock)
    monkeypatch.setattr(refresh_sources, "SessionLocal", lambda: _SessionContext())
    monkeypatch.setattr(refresh_sources, "due_source_runs", lambda *_args, **_kwargs: [run])
    monkeypatch.setattr(refresh_sources, "_runtime_release_gate", lambda _url: (True, "ok"))
    monkeypatch.setattr(refresh_sources, "_source_category", lambda _name: SourceCategory.JOB)

    def fake_run_command(label: str, _args: list[str]):
        calls.append(label)
        rc = 1 if label == postprocess_failure else 0
        return refresh_sources.CommandResult(label=label, returncode=rc)

    monkeypatch.setattr(refresh_sources, "_run_command", fake_run_command)
    monkeypatch.setattr(
        refresh_sources,
        "_publish_job_catalog_refresh",
        lambda sources: published.append(list(sources)),
    )
    return lock, calls, published


def test_job_invalidation_is_published_only_after_all_postprocess_succeeds(monkeypatch) -> None:
    lock, calls, published = _configure_main(monkeypatch, postprocess_failure=None)

    refresh_sources.main()

    assert calls == [
        "source:example-jobs:incremental",
        "postprocess:job-locations",
        "postprocess:job-location-propagation",
        "postprocess:job-concepts",
    ]
    assert published == [["example-jobs"]]
    assert lock.closed is True


def test_failed_job_postprocess_does_not_publish_intermediate_invalidation(monkeypatch) -> None:
    lock, _calls, published = _configure_main(
        monkeypatch,
        postprocess_failure="postprocess:job-concepts",
    )

    with pytest.raises(SystemExit) as exc:
        refresh_sources.main()

    assert exc.value.code == 1
    assert published == []
    assert lock.closed is True
