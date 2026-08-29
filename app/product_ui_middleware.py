from __future__ import annotations

import html
import re
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from app.database import SessionLocal
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


def _inject_product_chrome(body: bytes, *, notice: str | None) -> bytes:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body

    if "<main>" in text and "ww-product-brand" not in text:
        text = text.replace("<main>", "<main>\n" + _brand_html(), 1)

    if notice and "ww-geo-warning" not in text:
        warning = (
            '<aside class="ww-geo-warning" role="note">'
            "<strong>Standort nur eingeschränkt genau</strong>"
            + html.escape(notice)
            + "</aside>"
        )
        marker = "</section>"
        if '<section class="job-head">' in text and marker in text:
            text = text.replace(marker, marker + "\n" + warning, 1)
    return text.encode("utf-8")


class ProductUiMiddleware:
    """Inject product identity and explicit geo-precision warnings into HTML pages."""

    def __init__(self, app: Callable[..., Awaitable[Any]]) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        match = _JOB_DETAIL_PATH_RE.match(path)
        notice = _job_geo_notice(int(match.group("job_id"))) if match else None
        is_html = False

        async def send_wrapper(message) -> None:
            nonlocal is_html
            if message.get("type") == "http.response.start":
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
                    message = dict(message)
                    message["body"] = _inject_product_chrome(body, notice=notice)
            await send(message)

        await self.app(scope, receive, send_wrapper)
