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
_source_command = MODULE._source_command


def _run(source_name: str, *, reconciliation: bool) -> DueSourceRun:
    return DueSourceRun(
        plan=SourceRefreshPlan(
            source_name=source_name,
            script=f"scripts/run_{source_name.replace('.', '_')}.py",
            supports_reconciliation=True,
        ),
        reconciliation=reconciliation,
    )


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
