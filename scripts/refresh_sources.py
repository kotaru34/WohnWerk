from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Source, SourceCategory
from app.refresh import DueSourceRun, due_source_runs

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_PATH = Path("/run/wohnwerk-refresh/refresh.lock")


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
