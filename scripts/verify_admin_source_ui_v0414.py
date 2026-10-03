from __future__ import annotations

import argparse
import html
import subprocess

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.main import app
from app.models import CrawlRun, RunStatus, Source

EXPECTED_HEAD = "bc223ff2aa17306528300d4d3e31ad4180ca19fa"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def source_section(document: str) -> str:
    start = document.find("<h2>Quellen</h2>")
    end = document.find("<h2>Wert der Stellenquellen</h2>", start)
    require(start >= 0 and end > start, "could not isolate admin source section")
    return document[start:end]


def card_for_source(document: str, source: Source) -> str:
    section = source_section(document)
    marker = f'id="source-{source.id}"'
    marker_at = section.find(marker)
    require(marker_at >= 0, f"admin page missing source card {source.name}")
    start = section.rfind("<article", 0, marker_at)
    end = section.find("</article>", marker_at)
    require(start >= 0 and end >= 0, f"could not isolate source card {source.name}")
    card = section[start : end + len("</article>")]
    require(html.escape(source.name) in card, f"source card name mismatch for {source.name}")
    return card


def render_admin(mode: str) -> str:
    settings = get_settings()
    require(bool(settings.admin_password), "admin password is not configured")

    if mode == "local":
        with TestClient(app) as client:
            response = client.get(
                "/admin/health",
                auth=(settings.admin_username, settings.admin_password),
            )
    else:
        with httpx.Client(
            base_url="http://127.0.0.1:8000",
            auth=(settings.admin_username, settings.admin_password),
            timeout=15.0,
            follow_redirects=True,
        ) as client:
            response = client.get("/admin/health")

    require(response.status_code == 200, f"admin health HTTP {response.status_code}")
    return response.text


def validate_ui(document: str) -> tuple[int, str]:
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

    section = source_section(document)
    for needle in (
        'class="source-list"',
        'class="source-card"',
        "Details &amp; Diagnose",
        "Jetzt ausführen",
        "automatisch",
        "nur manuell",
    ):
        require(needle in section, f"admin source section missing {needle!r}")

    # The wide v0.4.13 source table must be gone from this section.
    require("<table" not in section, "legacy wide source table is still rendered")
    require("<th>Zustand / Grund</th>" not in section, "legacy source-table headers remain")
    require("<th>Fehlerdetails</th>" not in section, "legacy error column remains")

    falc = card_for_source(document, sources["falc-de"])
    require("automatisch" in falc, "falc-de is not shown as automatic")
    require("Jetzt ausführen" in falc, "falc-de run-now control missing")
    require("Deaktivieren" in falc, "falc-de disable control missing")
    require("Details &amp; Diagnose" in falc, "falc-de details disclosure missing")
    falc_run = latest_runs["falc-de"]
    require(falc_run is not None, "falc-de latest run missing")
    require(falc_run.status == RunStatus.SUCCESS, "falc-de latest run is not successful")
    require(f"#{falc_run.id}" in falc and "success" in falc, "falc-de latest-run telemetry missing")

    remax = card_for_source(document, sources["remax-de"])
    require("nur manuell" in remax, "remax-de is not shown as manual-only")
    require("Turnstile" in remax, "remax-de Turnstile reason missing")
    require("Jetzt ausführen" in remax, "remax-de run-now control missing")
    remax_details = remax.split('<details class="source-details">', 1)
    require(len(remax_details) == 2, "remax-de details disclosure missing")
    require(
        "Shard:" in remax_details[1] or "Lauf:" in remax_details[1],
        "remax-de full failure details are not inside the collapsed diagnostic block",
    )

    scout = card_for_source(document, sources["immoscout24-de"])
    require("nur manuell" in scout, "immoscout24-de is not shown as manual-only")
    require("Challenge" in scout, "immoscout24-de challenge reason missing")
    require("Jetzt ausführen" in scout, "immoscout24-de run-now control missing")
    scout_details = scout.split('<details class="source-details">', 1)
    require(len(scout_details) == 2, "immoscout24-de details disclosure missing")
    require(
        "Shard:" in scout_details[1] or "Lauf:" in scout_details[1],
        "immoscout24-de full failure details are not inside the collapsed diagnostic block",
    )

    immowelt = card_for_source(document, sources["immowelt-de"])
    require("automatisch" in immowelt, "immowelt-de is not shown as automatic")

    iad = card_for_source(document, sources["iad-de"])
    require("automatisch" in iad, "iad-de is not shown as automatic")

    return falc_run.id, ",".join(wanted)


def validate_live_invariants() -> None:
    head = subprocess.run(
        ["git", "-c", "safe.directory=/opt/wohnwerk", "-C", "/opt/wohnwerk", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    require(head == EXPECTED_HEAD, f"production HEAD mismatch: {head}")

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
    payload = health.json()
    require(payload.get("status") == "ok", "health status is not ok")
    require(payload.get("version") == "0.4.14", "health version is not v0.4.14")

    print(f"production_head={head} worktree=clean")
    print("units=active,active,active,active")
    print("health=ok version=0.4.14")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("local", "live"), required=True)
    args = parser.parse_args()

    document = render_admin(args.mode)
    falc_run_id, sources = validate_ui(document)

    print("admin_http=200")
    print(f"sources={sources}")
    print(f"falc_latest_run={falc_run_id} status=success")
    print("layout=source-cards legacy-source-table=absent")
    print("details=collapsed-diagnostics-present")
    print("controls=run-now enable-disable present")
    if args.mode == "live":
        validate_live_invariants()
        print("admin_source_ui_live_acceptance=ok")
    else:
        print("admin_source_ui_candidate_render=ok")


if __name__ == "__main__":
    main()
