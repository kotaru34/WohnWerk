from __future__ import annotations

import html

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Source


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
    require(
        "Letzter Lauf erfolgreich" in falc
        and "Frontier-Scan" in falc
        and "Disappearance-Authority" in falc,
        "falc-de bounded coverage explanation missing",
    )

    remax = row_for_source(document, "remax-de")
    require("nur manuell" in remax, "remax-de is not shown as manual-only")
    require("Turnstile" in remax, "remax-de Turnstile reason missing")
    require("Jetzt ausführen" in remax, "remax-de run-now control missing")

    scout = row_for_source(document, "immoscout24-de")
    require("nur manuell" in scout, "immoscout24-de is not shown as manual-only")
    require("Challenge" in scout, "immoscout24-de challenge reason missing")
    require("Jetzt ausführen" in scout, "immoscout24-de run-now control missing")

    immowelt = row_for_source(document, "immowelt-de")
    require("automatisch" in immowelt, "immowelt-de is not shown as automatic")

    iad = row_for_source(document, "iad-de")
    require("automatisch" in iad, "iad-de is not shown as automatic")

    print("admin_http=200")
    print("sources=" + ",".join(wanted))
    print("falc=automatic run-now disable bounded-reason-ok")
    print("remax=manual-only turnstile-reason run-now-ok")
    print("immoscout24=manual-only challenge-reason run-now-ok")
    print("immowelt=automatic")
    print("iad=automatic")
    print("admin_source_ops_acceptance=ok")


if __name__ == "__main__":
    main()
