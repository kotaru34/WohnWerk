from __future__ import annotations

import html
import subprocess

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import CrawlRun, RunStatus, Source


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def row_for_source(document: str, source_name: str) -> str:
    marker = f"<strong>{html.escape(source_name)}</strong>"
    marker_at = document.find(marker)
    require(marker_at >= 0, f"admin page missing source row {source_name}")
    start = document.rfind("<tr>", 0, marker_at)
    end = document.find("</tr>", marker_at)
    require(start >= 0 and end >= 0, f"could not isolate source row {source_name}")
    return document[start : end + len("</tr>")]


def main() -> None:
    wanted = ("falc-de", "iad-de", "immowelt-de", "remax-de", "immoscout24-de")
    with SessionLocal() as session:
        sources = {
            source.name: source
            for source in session.scalars(select(Source).where(Source.name.in_(wanted)))
        }
        latest_runs = {
            name: session.scalar(
                select(CrawlRun)
                .where(CrawlRun.source_id == source.id)
                .order_by(CrawlRun.started_at.desc(), CrawlRun.id.desc())
                .limit(1)
            )
            for name, source in sources.items()
        }

    missing = [name for name in wanted if name not in sources]
    require(not missing, "production source rows missing: " + ", ".join(missing))

    settings = get_settings()
    require(bool(settings.admin_password), "admin password is not configured")
    with httpx.Client(
        base_url="http://127.0.0.1:8000",
        auth=(settings.admin_username, settings.admin_password),
        timeout=15.0,
        follow_redirects=True,
    ) as client:
        response = client.get("/admin/health")

    require(response.status_code == 200, f"admin health HTTP {response.status_code}")
    document = response.text
    for needle in (
        "Betriebsübersicht",
        "Zustand / Grund",
        "Fehlerdetails",
        "Aktionen",
        "Jetzt ausführen",
        "automatisch",
        "nur manuell",
    ):
        require(needle in document, f"admin health missing {needle!r}")

    falc = row_for_source(document, "falc-de")
    require("automatisch" in falc, "falc-de is not shown as automatic")
    require("Jetzt ausführen" in falc, "falc-de run-now control missing")
    require("Deaktivieren" in falc, "falc-de disable control missing")
    falc_run = latest_runs["falc-de"]
    require(falc_run is not None, "falc-de latest run missing")
    require(falc_run.status == RunStatus.SUCCESS, "falc-de latest run is not successful")
    require(f"#{falc_run.id}" in falc and "success" in falc, "falc-de latest run telemetry missing")

    remax = row_for_source(document, "remax-de")
    require("nur manuell" in remax, "remax-de is not shown as manual-only")
    require("Turnstile" in remax, "remax-de Turnstile reason missing")
    require("Jetzt ausführen" in remax, "remax-de run-now control missing")
    require("Lauf:" in remax or "Shard:" in remax, "remax-de failure details missing")

    scout = row_for_source(document, "immoscout24-de")
    require("nur manuell" in scout, "immoscout24-de is not shown as manual-only")
    require("Challenge" in scout, "immoscout24-de challenge reason missing")
    require("Jetzt ausführen" in scout, "immoscout24-de run-now control missing")
    require("Lauf:" in scout or "Shard:" in scout, "immoscout24-de failure details missing")

    immowelt = row_for_source(document, "immowelt-de")
    require("automatisch" in immowelt, "immowelt-de is not shown as automatic")

    iad = row_for_source(document, "iad-de")
    require("automatisch" in iad, "iad-de is not shown as automatic")

    expected_head = "2863c01004341e9e7aa28bbc830c4e482e94c2df"
    head = subprocess.run(
        ["git", "-c", "safe.directory=/opt/wohnwerk", "-C", "/opt/wohnwerk", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    require(head == expected_head, f"production HEAD mismatch: {head}")

    dirty = subprocess.run(
        ["git", "-c", "safe.directory=/opt/wohnwerk", "-C", "/opt/wohnwerk", "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    require(not dirty, "production worktree is dirty")

    units = subprocess.run(
        [
            "systemctl",
            "is-active",
            "wohnwerk.service",
            "wohnwerk-refresh.timer",
            "wohnwerk-images.timer",
            "wohnwerk-liveness.timer",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    require(units == ["active"] * 4, f"unexpected unit state: {units!r}")

    health = httpx.get("http://127.0.0.1:8000/health", timeout=5.0)
    require(health.status_code == 200, f"health HTTP {health.status_code}")
    health_payload = health.json()
    require(health_payload.get("status") == "ok", "health status is not ok")
    require(health_payload.get("version") == "0.4.13", "health version is not v0.4.13")

    print("admin_http=200")
    print("sources=" + ",".join(wanted))
    print(f"falc=automatic run-now disable latest_run={falc_run.id} status={falc_run.status}")
    print("remax=manual-only turnstile-reason run-now-ok")
    print("immoscout24=manual-only challenge-reason run-now-ok")
    print("immowelt=automatic")
    print("iad=automatic")
    print(f"production_head={head} worktree=clean")
    print("units=active,active,active,active")
    print("health=ok version=0.4.13")
    print("admin_source_ops_acceptance=ok")


if __name__ == "__main__":
    main()
