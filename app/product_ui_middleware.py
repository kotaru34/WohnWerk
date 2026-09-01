from __future__ import annotations

import html
import re
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from app.database import SessionLocal
from app.live_events import latest_live_event_id
from app.models import JobLocation
from app.version import __version__

_JOB_DETAIL_PATH_RE = re.compile(r"^/jobs/(?P<job_id>\d+)$")
_DIRECTIONAL_RE = re.compile(
    r"^(?P<direction>nördlich|noerdlich|südlich|suedlich|östlich|oestlich|westlich)\s+von\s+"
    r"(?P<anchor>.+)$",
    re.IGNORECASE,
)
_VAGUE_AREA_RE = re.compile(
    r"(?:\bgroßraum\b|\bgrossraum\b|\bumgebung\b|\bzentralraum\b|"
    r"\bregion\b|\braum\s+[^,]+|österreichweit|oesterreichweit)",
    re.IGNORECASE,
)
_BROAD_REGION_ONLY_RE = re.compile(
    r"^\s*(?:burgenland|kärnten|kaernten|niederösterreich|niederoesterreich|"
    r"oberösterreich|oberoesterreich|steiermark|tirol|vorarlberg|österreich|austria)"
    r"(?:\s*,\s*(?:österreich|austria))?\s*$",
    re.IGNORECASE,
)

_BRAND_STYLE = """
<style id="wohnwerk-product-brand-style">
  .ww-product-brand {
    display: flex; align-items: baseline; gap: 10px; margin: 0 0 14px;
    line-height: 1;
  }
  .ww-product-brand-name { font-size: 1.7rem; font-weight: 820; letter-spacing: -.035em; }
  .ww-product-version {
    font-size: .74rem; opacity: .62; border: 1px solid color-mix(in srgb, CanvasText 18%, transparent);
    border-radius: 999px; padding: 4px 7px; letter-spacing: .03em;
  }
  .ww-geo-warning {
    margin: 14px 0 0; padding: 12px 14px;
    border: 1px solid color-mix(in srgb, #c69342 55%, CanvasText 14%);
    border-radius: 10px; background: color-mix(in srgb, #c69342 10%, Canvas);
    font-size: .88rem; line-height: 1.45;
  }
  .ww-geo-warning strong { display: block; margin-bottom: 3px; }
</style>
""".strip()

_LIVE_SYNC_SCRIPT = r"""
<script id="wohnwerk-live-sync">
(() => {
  if (!("EventSource" in window)) return;
  const initialCursor = __CURSOR__;
  const path = window.location.pathname;
  const isDetail = /^\/(?:houses|jobs)\/\d+$/.test(path);
  const topics = isDetail
    ? new Set(["houses", "jobs", "all"])
    : path.startsWith("/houses")
      ? new Set(["houses", "all"])
      : path.startsWith("/jobs")
        ? new Set(["jobs", "all"])
        : new Set();
  if (!topics.size) return;

  let refreshTimer = null;
  let refreshing = false;
  let dirtyDuringRefresh = false;
  let deferredForEditing = false;

  const editing = () => {
    const active = document.activeElement;
    if (!active || !active.closest("main")) return false;
    return active.matches("input, select, textarea, [contenteditable='true']");
  };

  const refreshMain = async () => {
    refreshTimer = null;
    if (editing()) {
      deferredForEditing = true;
      return;
    }
    if (refreshing) {
      dirtyDuringRefresh = true;
      return;
    }

    refreshing = true;
    dirtyDuringRefresh = false;
    try {
      const response = await fetch(window.location.href, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          "Accept": "text/html",
          "X-WohnWerk-Live-Refresh": "1"
        }
      });
      if (!response.ok) return;
      const incoming = new DOMParser().parseFromString(await response.text(), "text/html");
      const nextMain = incoming.querySelector("main");
      const currentMain = document.querySelector("main");
      if (!nextMain || !currentMain) return;
      currentMain.replaceWith(nextMain);
      if (incoming.title) document.title = incoming.title;
    } catch (_error) {
      // EventSource reconnect and the next invalidation will retry naturally.
    } finally {
      refreshing = false;
      if (dirtyDuringRefresh) scheduleRefresh();
    }
  };

  const scheduleRefresh = () => {
    if (refreshing) {
      dirtyDuringRefresh = true;
      return;
    }
    if (editing()) {
      deferredForEditing = true;
      return;
    }
    if (refreshTimer !== null) return;
    refreshTimer = window.setTimeout(refreshMain, 180);
  };

  document.addEventListener("focusout", () => {
    if (!deferredForEditing) return;
    window.setTimeout(() => {
      if (!editing()) {
        deferredForEditing = false;
        scheduleRefresh();
      }
    }, 80);
  }, true);

  const stream = new EventSource(`/events?after=${initialCursor}`);
  stream.addEventListener("invalidate", (event) => {
    try {
      const message = JSON.parse(event.data);
      if (topics.has(message.topic)) scheduleRefresh();
    } catch (_error) {
      // Ignore malformed invalidations; a later valid event can still refresh the page.
    }
  });

  window.addEventListener("beforeunload", () => stream.close(), {once: true});
})();
</script>
""".strip()


def _brand_html() -> str:
    return (
        _BRAND_STYLE
        + '<header class="ww-product-brand" aria-label="WohnWerk Version">'
        + '<span class="ww-product-brand-name">WohnWerk</span>'
        + f'<span class="ww-product-version">v{html.escape(__version__)}</span>'
        + "</header>"
    )


def _location_label(location: JobLocation) -> str:
    return (
        (location.city or "").strip()
        or (location.location_text or "").strip()
        or (location.postal_code or "").strip()
        or "unbekannte Quellenangabe"
    )


def _job_geo_notice(job_id: int) -> str | None:
    with SessionLocal() as session:
        locations = list(
            session.scalars(
                select(JobLocation)
                .where(JobLocation.job_id == job_id)
                .order_by(JobLocation.id)
            )
        )

    if not locations:
        return (
            "Für diese Stelle ist keine belastbare Standortangabe gespeichert. "
            "Entfernungen zu Häusern können deshalb nicht zuverlässig berechnet werden."
        )

    for location in locations:
        city = (location.city or "").strip()
        directional = _DIRECTIONAL_RE.match(city)
        if directional:
            anchor = directional.group("anchor").strip()
            if location.location is not None:
                return (
                    f"Die Quelle nennt den Arbeitsort nur als „{city}“. WohnWerk verwendet für "
                    f"Umkreisberechnungen näherungsweise den Mittelpunkt von {anchor}. Die "
                    "tatsächliche Arbeitsstelle kann deutlich davon abweichen."
                )
            return (
                f"Die Quelle nennt den Arbeitsort nur als „{city}“. WohnWerk konnte daraus "
                "keine verlässliche Geoposition bestimmen; Umkreisangaben können unvollständig sein."
            )

    resolved = [location for location in locations if location.location is not None]
    unresolved = [location for location in locations if location.location is None]
    vague = [location for location in locations if _VAGUE_AREA_RE.search(_location_label(location))]

    if vague and resolved:
        labels = ", ".join(dict.fromkeys(_location_label(location) for location in vague))
        return (
            f"Die Quelle nennt nur einen groben Bereich ({labels}). Die verwendete Geoposition ist "
            "eine Näherung; Entfernungen dienen nur zur Orientierung."
        )
    if not resolved and unresolved:
        labels = ", ".join(dict.fromkeys(_location_label(location) for location in unresolved))
        if all(_BROAD_REGION_ONLY_RE.match(_location_label(location)) for location in unresolved):
            return (
                f"Die Quelle nennt nur einen sehr groben Bereich („{labels}“). WohnWerk setzt "
                "dafür bewusst keinen künstlichen Mittelpunkt, weil eine Umkreissuche sonst "
                "irreführend wäre."
            )
        return (
            f"WohnWerk konnte die Quellenangabe „{labels}“ nicht verlässlich geokodieren. "
            "Die Umkreissuche kann deshalb leer oder unvollständig sein."
        )
    if resolved and unresolved:
        labels = ", ".join(dict.fromkeys(_location_label(location) for location in unresolved))
        return (
            f"Mindestens ein angegebener Arbeitsort konnte nicht geokodiert werden ({labels}). "
            "Die Umkreissuche berücksichtigt nur die verlässlich geokodierten Standorte."
        )
    return None


def _inject_product_chrome(
    body: bytes,
    *,
    notice: str | None,
    live_cursor: int | None = None,
) -> bytes:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body

    if "<main>" in text and '<header class="ww-product-brand"' not in text:
        text = text.replace("<main>", "<main>\n" + _brand_html(), 1)

    if notice and '<aside class="ww-geo-warning"' not in text:
        warning = (
            '<aside class="ww-geo-warning" role="note">'
            "<strong>Standort nur eingeschränkt genau</strong>"
            + html.escape(notice)
            + "</aside>"
        )
        marker = "</section>"
        if '<section class="job-head">' in text and marker in text:
            text = text.replace(marker, marker + "\n" + warning, 1)

    if (
        live_cursor is not None
        and "</body>" in text
        and 'id="wohnwerk-live-sync"' not in text
    ):
        script = _LIVE_SYNC_SCRIPT.replace("__CURSOR__", str(max(0, live_cursor)))
        text = text.replace("</body>", script + "\n</body>", 1)
    return text.encode("utf-8")


def _live_product_path(path: str, method: str) -> bool:
    if method.upper() != "GET":
        return False
    return path in {"/houses", "/jobs"} or path.startswith(("/houses/", "/jobs/"))


def _has_authorization(scope) -> bool:
    return any(key.lower() == b"authorization" for key, _value in scope.get("headers") or [])


class ProductUiMiddleware:
    """Inject product identity, geo warnings and live synchronization into product HTML."""

    def __init__(self, app: Callable[..., Awaitable[Any]]) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "GET")
        match = _JOB_DETAIL_PATH_RE.match(path)
        job_id = int(match.group("job_id")) if match else None
        live_cursor: int | None = None
        if _live_product_path(path, method) and _has_authorization(scope):
            with SessionLocal() as session:
                live_cursor = latest_live_event_id(session)

        is_html = False
        response_status = 0

        async def send_wrapper(message) -> None:
            nonlocal is_html, response_status
            if message.get("type") == "http.response.start":
                response_status = int(message.get("status") or 0)
                headers = list(message.get("headers") or [])
                is_html = any(
                    key.lower() == b"content-type" and b"text/html" in value.lower()
                    for key, value in headers
                )
                if is_html:
                    message = dict(message)
                    message["headers"] = [
                        (key, value) for key, value in headers if key.lower() != b"content-length"
                    ]
            elif message.get("type") == "http.response.body" and is_html:
                body = message.get("body") or b""
                if body:
                    notice = (
                        _job_geo_notice(job_id)
                        if job_id is not None and 200 <= response_status < 300
                        else None
                    )
                    message = dict(message)
                    message["body"] = _inject_product_chrome(
                        body,
                        notice=notice,
                        live_cursor=live_cursor,
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)
