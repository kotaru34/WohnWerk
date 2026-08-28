from __future__ import annotations

from urllib.parse import parse_qsl, urlencode

HOUSE_OPTIONAL_NUMERIC_FILTERS = frozenset(
    {
        "preis_von",
        "preis_bis",
        "wohn_von",
        "wohn_bis",
        "grund_von",
        "grund_bis",
    }
)


def normalize_house_query_string(query_string: bytes) -> bytes:
    """Drop blank optional numeric house filters before FastAPI validation."""
    if not query_string:
        return query_string

    pairs = parse_qsl(query_string.decode("utf-8"), keep_blank_values=True)
    normalized = [
        (key, value)
        for key, value in pairs
        if not (key in HOUSE_OPTIONAL_NUMERIC_FILTERS and not value.strip())
    ]
    if normalized == pairs:
        return query_string
    return urlencode(normalized, doseq=True).encode("utf-8")


class NormalizeHouseQueryMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/houses":
            normalized = normalize_house_query_string(scope.get("query_string", b""))
            if normalized != scope.get("query_string", b""):
                scope = dict(scope)
                scope["query_string"] = normalized
        await self.app(scope, receive, send)
