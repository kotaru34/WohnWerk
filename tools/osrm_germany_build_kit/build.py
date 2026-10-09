#!/usr/bin/env python3
"""Build and locally accept a Germany OSRM MLD graph using Docker/Podman.

Designed for Windows MSYS2 + Docker Desktop/Podman or Debian. No production
access. Input and container provenance are recorded in a manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

IMAGE = "ghcr.io/project-osrm/osrm-backend:26.10.0-debian"
PBF_URL = "https://download.geofabrik.de/europe/germany-latest.osm.pbf"
MD5_URL = PBF_URL + ".md5"
PBF_NAME = "germany-latest.osm.pbf"
GRAPH_PREFIX = "germany-latest.osrm"
MIN_FREE_GIB_WARNING = 60.0
RAM_GIB_WARNING = 32.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def md5(path: Path) -> str:  # noqa: S324 - checksum verifies publisher sidecar, not security
    digest = hashlib.md5()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(argv), flush=True)
    return subprocess.run(
        argv,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture,
        timeout=timeout,
    )


def engine() -> str:
    for candidate in ("docker", "podman"):
        if shutil.which(candidate):
            return candidate
    raise RuntimeError("Docker or Podman is required and must be on PATH")


def host_volume_path(path: Path) -> str:
    resolved = path.resolve()
    cygpath = shutil.which("cygpath")
    if cygpath:
        try:
            converted = subprocess.run(
                [cygpath, "-w", str(resolved)],
                check=True,
                text=True,
                capture_output=True,
                timeout=5,
            ).stdout.strip()
            if converted:
                return converted
        except (OSError, subprocess.SubprocessError):
            pass
    return str(resolved)


def download(url: str, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size:
        print(f"Using existing {destination.name} ({destination.stat().st_size:,} bytes)")
        return
    tmp = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "WohnWerk-OSRM-build-kit/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response, tmp.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        last = time.monotonic()
        while True:
            block = response.read(4 * 1024 * 1024)
            if not block:
                break
            out.write(block)
            received += len(block)
            now = time.monotonic()
            if now - last >= 5:
                if total:
                    print(f"  {received / 1024**3:.2f}/{total / 1024**3:.2f} GiB")
                else:
                    print(f"  {received / 1024**3:.2f} GiB")
                last = now
    os.replace(tmp, destination)


def expected_md5(sidecar: Path) -> str:
    token = sidecar.read_text(encoding="ascii", errors="strict").split()[0].strip().lower()
    if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        raise RuntimeError("Invalid Geofabrik MD5 sidecar")
    return token


def container_memory_bytes(tool: str) -> int | None:
    if tool != "docker":
        return None
    try:
        value = run(
            [tool, "info", "--format", "{{.MemTotal}}"],
            capture=True,
            timeout=15,
        ).stdout.strip()
        return int(value)
    except (ValueError, subprocess.SubprocessError):
        return None


def image_provenance(tool: str) -> dict[str, object]:
    run([tool, "pull", IMAGE], timeout=600)
    inspect = run(
        [tool, "image", "inspect", IMAGE, "--format", "{{json .RepoDigests}}"],
        capture=True,
        timeout=20,
    ).stdout.strip()
    try:
        repo_digests = json.loads(inspect)
    except json.JSONDecodeError:
        repo_digests = []
    version = run(
        [tool, "run", "--rm", IMAGE, "osrm-routed", "--version"],
        capture=True,
        timeout=30,
    ).stdout.strip()
    return {
        "requested_image": IMAGE,
        "repo_digests": repo_digests,
        "osrm_version": version,
    }


def docker_run(tool: str, work: Path, args: list[str], *, timeout: int | None = None) -> None:
    mount = f"{host_volume_path(work)}:/data"
    run([tool, "run", "--rm", "-t", "-v", mount, IMAGE, *args], timeout=timeout)


def graph_artifacts(work: Path) -> list[Path]:
    return sorted(
        path for path in work.glob(f"{GRAPH_PREFIX}*")
        if path.is_file() and path.name != f"{GRAPH_PREFIX}.pbf"
    )


def required_inputs(tool: str, work: Path) -> list[str]:
    proc = run(
        [tool, "run", "--rm", IMAGE, "osrm-routed", "--list-inputs"],
        capture=True,
        timeout=30,
    )
    suffixes = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return [GRAPH_PREFIX + suffix for suffix in suffixes]


def start_router(tool: str, work: Path, name: str) -> None:
    mount = f"{host_volume_path(work)}:/data"
    run([
        tool, "run", "--rm", "-d", "--name", name,
        "-p", "127.0.0.1:5000:5000",
        "-v", mount,
        IMAGE,
        "osrm-routed", "--algorithm", "mld",
        "--max-table-size", "100",
        f"/data/{GRAPH_PREFIX}",
    ], timeout=60)


def wait_for_router(timeout_seconds: int = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    url = "http://127.0.0.1:5000/nearest/v1/driving/11.5755,48.1374?number=1"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                payload = json.load(response)
            if response.status == 200 and payload.get("code") == "Ok":
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("local OSRM did not become ready")


def memory_stat(tool: str, name: str) -> str | None:
    if tool != "docker":
        return None
    try:
        return run(
            [tool, "stats", "--no-stream", "--format", "{{.MemUsage}}", name],
            capture=True,
            timeout=15,
        ).stdout.strip()
    except subprocess.SubprocessError:
        return None


def verify_router(work: Path) -> dict[str, object]:
    verify_script = Path(__file__).with_name("verify.py")
    report = work / "wohnwerk-osrm-acceptance.json"
    run([
        sys.executable,
        str(verify_script),
        "--base-url", "http://127.0.0.1:5000",
        "--json-out", str(report),
    ], timeout=120)
    return json.loads(report.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    work = args.work_dir.expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    tool = engine()

    free_gib = shutil.disk_usage(work).free / 1024**3
    if free_gib < MIN_FREE_GIB_WARNING:
        print(
            f"WARNING: only {free_gib:.1f} GiB free; Germany build may need much more "
            f"than {MIN_FREE_GIB_WARNING:.0f} GiB.",
            file=sys.stderr,
        )
    mem = container_memory_bytes(tool)
    if mem is not None and mem / 1024**3 < RAM_GIB_WARNING:
        print(
            f"WARNING: container runtime exposes only {mem / 1024**3:.1f} GiB RAM. "
            f"Germany preprocessing may fail; {RAM_GIB_WARNING:.0f} GiB+ is recommended "
            "for a first attempt.",
            file=sys.stderr,
        )

    pbf = work / PBF_NAME
    sidecar = work / (PBF_NAME + ".md5")
    if not args.skip_download:
        download(MD5_URL, sidecar)
        download(PBF_URL, pbf)
    if not pbf.is_file() or not sidecar.is_file():
        raise RuntimeError("PBF and .md5 sidecar must exist")
    published_md5 = expected_md5(sidecar)
    actual_md5 = md5(pbf)
    if published_md5 != actual_md5:
        raise RuntimeError(
            f"Geofabrik checksum mismatch: expected {published_md5}, got {actual_md5}"
        )
    pbf_sha256 = sha256(pbf)

    image = image_provenance(tool)

    if not args.skip_build:
        for old in graph_artifacts(work):
            old.unlink()
        docker_run(
            tool, work,
            ["osrm-extract", "-p", "/opt/car.lua", f"/data/{PBF_NAME}"],
            timeout=None,
        )
        docker_run(tool, work, ["osrm-partition", f"/data/{GRAPH_PREFIX}"], timeout=None)
        docker_run(tool, work, ["osrm-customize", f"/data/{GRAPH_PREFIX}"], timeout=None)

    artifacts = graph_artifacts(work)
    if not artifacts:
        raise RuntimeError("no Germany OSRM graph artifacts were produced")

    required = required_inputs(tool, work)
    missing = [name for name in required if not (work / name).is_file()]
    if missing:
        raise RuntimeError(f"missing osrm-routed inputs: {missing}")

    name = f"wohnwerk-osrm-germany-verify-{os.getpid()}"
    acceptance: dict[str, object]
    mem_stat: str | None = None
    try:
        start_router(tool, work, name)
        wait_for_router()
        mem_stat = memory_stat(tool, name)
        acceptance = verify_router(work)
    finally:
        subprocess.run([tool, "rm", "-f", name], check=False, capture_output=True)

    artifact_rows = [
        {
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in artifacts
    ]
    manifest = {
        "schema": "wohnwerk-osrm-germany-package-v1",
        "state": "built_and_locally_accepted_not_deployed",
        "country": "DE",
        "algorithm": "MLD",
        "profile": "/opt/car.lua",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source": {
            "url": PBF_URL,
            "md5_url": MD5_URL,
            "published_md5": published_md5,
            "sha256": pbf_sha256,
            "bytes": pbf.stat().st_size,
        },
        "container": image,
        "builder": {
            "engine": tool,
            "free_disk_gib_at_start": round(free_gib, 2),
            "container_mem_total_bytes": mem,
        },
        "router_loaded_memory": mem_stat,
        "required_inputs": required,
        "artifacts": artifact_rows,
        "acceptance": acceptance,
    }
    manifest_path = work / "wohnwerk-osrm-germany-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nSUCCESS: {manifest_path}")
    print("Graph is locally accepted but NOT deployed or authorized for production.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
