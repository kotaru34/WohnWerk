from app.refresh import DueSourceRun, SourceRefreshPlan
from scripts.refresh_sources import _source_command


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
