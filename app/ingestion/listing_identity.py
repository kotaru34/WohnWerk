from __future__ import annotations

import re
from urllib.parse import urlparse

SREAL_DETAIL_RE = re.compile(r"^/de/immobilie/(?P<listing_id>[^/]+)/", re.IGNORECASE)


def stable_external_identity(url: str) -> str | None:
    """Return a provider-issued stable listing identity when it is unambiguous.

    This is deliberately provider-specific. Generic URL normalization can incorrectly
    merge unrelated pages, while s REAL embeds its stable object ID directly in every
    detail URL regardless of scheme, www host, slug or query parameters.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if host in {"sreal.at", "www.sreal.at"}:
        match = SREAL_DETAIL_RE.match(parsed.path)
        if match is not None:
            return f"sreal.at:{match.group('listing_id').casefold()}"
    return None
