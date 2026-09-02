from __future__ import annotations

from contextvars import ContextVar
from html import escape
from http.cookies import CookieError, SimpleCookie
from urllib.parse import parse_qsl, urlencode

from sqlalchemy import event, exists, func, select
from sqlalchemy.orm import Session, with_loader_criteria

from app.models import Job, JobListing, ListingStatus, Property, PropertyListing, Source

SUPPORTED_COUNTRIES = ("DE", "AT")
DEFAULT_COUNTRY = "AT"
COOKIE_NAME = "wohnwerk_country"
_SCOPED_PREFIXES = ("/houses", "/jobs", "/matches")
_selected_country: ContextVar[str | None] = ContextVar("wohnwerk_country", default=None)


def normalize_country(value: str | None) -> str | None:
    if not value:
        return None
    code = value.strip().upper()
    return code if code in SUPPORTED_COUNTRIES else None


def selected_country() -> str | None:
    return _selected_country.get()


def _source_country_expression():
    # Existing Austria-only sources predate country metadata.  Treat an absent
    # value as AT so the frozen v1 corpus keeps its exact current semantics.
    return func.upper(func.coalesce(Source.config["country_code"].astext, DEFAULT_COUNTRY))


def _property_country_condition(country_code: str):
    return exists(
        select(PropertyListing.id)
        .join(Source, Source.id == PropertyListing.source_id)
        .where(
            PropertyListing.property_id == Property.id,
            PropertyListing.status == ListingStatus.ACTIVE,
            _source_country_expression() == country_code,
        )
    )


def _job_country_condition(country_code: str):
    return exists(
        select(JobListing.id)
        .join(Source, Source.id == JobListing.source_id)
        .where(
            JobListing.job_id == Job.id,
            JobListing.status == ListingStatus.ACTIVE,
            _source_country_expression() == country_code,
        )
    )


@event.listens_for(Session, "do_orm_execute")
def _apply_http_country_scope(execute_state) -> None:
    country_code = selected_country()
    if country_code is None or not execute_state.is_select:
        return

    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            Property,
            _property_country_condition(country_code),
            include_aliases=True,
        ),
        with_loader_criteria(
            Job,
            _job_country_condition(country_code),
            include_aliases=True,
        ),
    )


def _cookie_country(scope) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() != b"cookie":
            continue
        cookie = SimpleCookie()
        try:
            cookie.load(value.decode("latin-1"))
        except CookieError:
            return None
        morsel = cookie.get(COOKIE_NAME)
        return normalize_country(morsel.value if morsel else None)
    return None


def _country_href(scope, country_code: str) -> str:
    raw_query = scope.get("query_string", b"").decode("latin-1")
    pairs = [
        (key, value)
        for key, value in parse_qsl(raw_query, keep_blank_values=True)
        if key != "country"
    ]
    pairs.append(("country", country_code))
    path = scope.get("path", "/") or "/"
    return f"{path}?{urlencode(pairs)}"


def _switch_markup(scope, country_code: str) -> bytes:
    links = []
    for code, flag in (("DE", "🇩🇪"), ("AT", "🇦🇹")):
        active = " ww-country-active" if code == country_code else ""
        href = escape(_country_href(scope, code), quote=True)
        aria_current = "page" if code == country_code else "false"
        links.append(
            f'<a class="ww-country-option{active}" href="{href}" '
            f'aria-current="{aria_current}">{flag} {code}</a>'
        )
    markup = f"""
<style id="ww-country-style">
.ww-country-switch{{position:fixed;top:12px;left:12px;z-index:10000;display:flex;gap:4px;padding:4px;border:1px solid rgba(127,127,127,.32);border-radius:10px;background:rgba(20,20,22,.88);backdrop-filter:blur(8px);box-shadow:0 4px 18px rgba(0,0,0,.18)}}
.ww-country-option{{display:inline-flex;align-items:center;gap:5px;padding:6px 9px;border-radius:7px;color:#ddd;text-decoration:none;font:600 13px/1.1 system-ui,sans-serif;opacity:.66}}
.ww-country-option:hover{{opacity:1;background:rgba(255,255,255,.08)}}
.ww-country-option.ww-country-active{{opacity:1;color:#fff;background:rgba(255,255,255,.14)}}
</style>
<nav class="ww-country-switch" aria-label="Land auswählen">{''.join(links)}</nav>
"""
    return markup.encode("utf-8")


class CountryScopeMiddleware:
    """Persist DE/AT selection, scope ORM reads, and add the compact UI switch.

    The country is deliberately derived from Source.config["country_code"].  This
    avoids duplicating geography state on canonical Job/Property rows and lets one
    canonical object keep several source listings while UI selection remains a
    source/acquisition concern.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or not str(scope.get("path", "")).startswith(
            _SCOPED_PREFIXES
        ):
            await self.app(scope, receive, send)
            return

        query = dict(
            parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        )
        query_country = normalize_country(query.get("country"))
        country_code = query_country or _cookie_country(scope) or DEFAULT_COUNTRY
        token = _selected_country.set(country_code)

        pending_start = None
        buffer_html = False
        body_parts: list[bytes] = []

        async def scoped_send(message) -> None:
            nonlocal pending_start, buffer_html
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if query_country is not None:
                    cookie_value = (
                        f"{COOKIE_NAME}={country_code}; Path=/; SameSite=Lax; Max-Age=31536000"
                    )
                    headers.append((b"set-cookie", cookie_value.encode("latin-1")))
                content_type = next(
                    (
                        value.decode("latin-1").lower()
                        for key, value in headers
                        if key.lower() == b"content-type"
                    ),
                    "",
                )
                buffer_html = "text/html" in content_type
                message = {**message, "headers": headers}
                if buffer_html:
                    pending_start = message
                else:
                    await send(message)
                return

            if message["type"] != "http.response.body" or not buffer_html:
                await send(message)
                return

            body_parts.append(message.get("body", b""))
            if message.get("more_body", False):
                return

            body = b"".join(body_parts)
            switch = _switch_markup(scope, country_code)
            marker = b"</body>"
            if marker in body:
                body = body.replace(marker, switch + marker, 1)
            else:
                body += switch

            start = pending_start or {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            }
            headers = [
                (key, value)
                for key, value in start.get("headers", [])
                if key.lower() != b"content-length"
            ]
            headers.append((b"content-length", str(len(body)).encode("ascii")))
            await send({**start, "headers": headers})
            await send({"type": "http.response.body", "body": body, "more_body": False})

        try:
            await self.app(scope, receive, scoped_send)
        finally:
            _selected_country.reset(token)
