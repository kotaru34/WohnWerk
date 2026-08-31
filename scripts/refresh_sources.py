from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import httpx
from sqlalchemy import select

from app.database import SessionLocal
from app.jobs.concept_catalog import EXTRACTOR_VERSION
from app.models import Source, SourceCategory
from app.refresh import DueSourceRun, due_source_runs
from app.version import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_PATH = Path("/run/wohnwerk-refresh/refresh.lock")
DEFAULT_HEALTH_URL = "http://127.0.0.1:8000/health"


@dataclass(frozen=True, slots=True)
class CommandResult:
    label: str
    returncode: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run due WohnWerk acquisition sources and refresh derived job matching data. "
            "Source poll/reconciliation cadence is read from the database."
        )
    )
    parser.add_argument(
        "--reconciliation-retry-minutes",
        type=int,
        default=180,
        help="Backoff after a reconciliation attempt before retrying an overdue source.",
    )
    parser.add_argument(
        "--lock-path",
        type=Path,
        default=DEFAULT_LOCK_PATH,
        help=f"Single-instance lock path (default: {DEFAULT_LOCK_PATH}).",
    )
    parser.add_argument(
        "--health-url",
        default=DEFAULT_HEALTH_URL,
        help=(
            "Running web health endpoint used to gate mutating refresh work "
            f"(default: {DEFAULT_HEALTH_URL})."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print due work without running source or post-processing commands.",
    )
    return parser.parse_args()


def _run_command(label: str, args: list[str]) -> CommandResult:
    print(f"===== {label} =====", flush=True)
    print("command=" + " ".join(args), flush=True)
    completed = subprocess.run(args, cwd=PROJECT_ROOT, check=False)
    print(f"result[{label}]={completed.returncode}", flush=True)
    return CommandResult(label=label, returncode=completed.returncode)


def _source_command(run: DueSourceRun) -> list[str]:
    args = [sys.executable, str(PROJECT_ROOT / run.plan.script)]
    if run.reconciliation:
        args.append("--reconcile")
        # s REAL has a small, authoritative corpus and a validated fail-soft detail
        # enricher. Fetch details only on the daily full scan so descriptions, exact
        # area metadata and source-backed preview images stay fresh without turning the
        # hourly incremental crawl into hundreds of extra requests.
        if run.plan.source_name == "sreal.at":
            args.append("--enrich-details")
    return args


def _runtime_release_gate(health_url: str) -> tuple[bool, str]:
    """Fail closed if this refresh process is newer/different than the running web reader."""

    try:
        response = httpx.get(health_url, timeout=3.0)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        print(f"runtime_gate_error={type(exc).__name__}:{exc}", flush=True)
        return False, "web_health_unavailable"

    if not isinstance(payload, dict):
        print(f"runtime_gate_error=invalid_payload_type:{type(payload).__name__}", flush=True)
        return False, "invalid_web_health"

    runtime_status = payload.get("status")
    runtime_service = payload.get("service")
    runtime_version = payload.get("version")
    runtime_extractor = payload.get("job_concept_extractor")

    print(f"refresh_code_version={__version__}", flush=True)
    print(f"refresh_code_extractor={EXTRACTOR_VERSION}", flush=True)
    print(f"runtime_service={runtime_service}", flush=True)
    print(f"runtime_status={runtime_status}", flush=True)
    print(f"runtime_version={runtime_version}", flush=True)
    print(f"runtime_extractor={runtime_extractor}", flush=True)

    if runtime_status != "ok" or runtime_service != "wohnwerk":
        return False, "invalid_web_health"
    if runtime_version != __version__:
        return False, "web_version_mismatch"
    if runtime_extractor != EXTRACTOR_VERSION:
        return False, "web_extractor_mismatch"
    return True, "ok"


def _acquire_lock(path: Path) -> TextIO | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def _source_category(source_name: str) -> str | None:
    with SessionLocal() as session:
        return session.scalar(select(Source.category).where(Source.name == source_name))


def main() -> None:
    args = parse_args()
    lock = _acquire_lock(args.lock_path)
    if lock is None:
        print("refresh_status=skipped reason=already_running")
        return

    try:
        with SessionLocal() as session:
            due = due_source_runs(
                session,
                reconciliation_retry_minutes=max(1, args.reconciliation_retry_minutes),
            )

        print(f"due_sources={len(due)}")
        for run in due:
            print(f"  source={run.plan.source_name} mode={run.mode} script={run.plan.script}")

        if args.dry_run:
            print("refresh_status=dry-run")
            return
        if not due:
            print("refresh_status=ok work=none")
            return

        runtime_ok, runtime_reason = _runtime_release_gate(args.health_url)
        if not runtime_ok:
            print(f"refresh_status=deferred reason={runtime_reason}")
            return

        failures: list[CommandResult] = []
        job_source_succeeded = False
        for run in due:
            result = _run_command(
                f"source:{run.plan.source_name}:{run.mode}",
                _source_command(run),
            )
            if result.returncode != 0:
                failures.append(result)
                continue
            if _source_category(run.plan.source_name) == SourceCategory.JOB:
                job_source_succeeded = True

        if job_source_succeeded:
            for label, command in (
                (
                    "postprocess:job-locations",
                    [sys.executable, str(PROJECT_ROOT / "scripts/resolve_job_locations.py")],
                ),
                (
                    "postprocess:job-location-propagation",
                    [
                        sys.executable,
                        str(PROJECT_ROOT / "scripts/propagate_job_location_resolutions.py"),
                    ],
                ),
                (
                    "postprocess:job-concepts",
                    [
                        sys.executable,
                        str(PROJECT_ROOT / "scripts/normalize_job_concepts.py"),
                        "--apply",
                    ],
                ),
            ):
                result = _run_command(label, command)
                if result.returncode != 0:
                    failures.append(result)

        if failures:
            print("refresh_status=partial")
            for failure in failures:
                print(f"failure={failure.label} rc={failure.returncode}")
            raise SystemExit(1)

        print("refresh_status=ok")
    finally:
        lock.close()


if __name__ == "__main__":
    main()
