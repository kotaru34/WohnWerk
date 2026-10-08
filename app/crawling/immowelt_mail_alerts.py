"""Offline parser for user-owned Immowelt Suchauftrag alert messages.

No network access, login, browser navigation or page scraping is performed.
This is a conservative URL-only input, not an authoritative property crawl.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

_IMMOWELT_HOSTS = frozenset({"immowelt.de", "www.immowelt.de"})
_EXPOSE_PATH = re.compile(r"^/expose/(?P<id>(?:[0-9a-f-]{20,}|[a-z0-9]{12}))/?$", re.IGNORECASE)
_HTTP_LINK = re.compile(r"https?://[^\s<>\"'()]+", re.IGNORECASE)
_TITLE_WS = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ImmoweltAlertListing:
    source_listing_id: str
    url: str
    title: str | None


def canonical_alert_url(raw: str) -> tuple[str, str] | None:
    """Only canonical public expose URLs, never click-tracking or offsite links."""
    try:
        parsed = urlsplit(raw.strip())
        if parsed.scheme.lower() != "https" or parsed.hostname not in _IMMOWELT_HOSTS:
            return None
        if parsed.username is not None or parsed.password is not None or parsed.port is not None:
            return None
        path = unquote(parsed.path)
        match = _EXPOSE_PATH.fullmatch(path)
        if match is None:
            return None
    except (ValueError, UnicodeError):
        return None
    listing_id = match.group("id").lower()
    return listing_id, f"https://www.immowelt.de/expose/{listing_id}"


def _clean_title(value: str) -> str | None:
    title = _TITLE_WS.sub(" ", value).strip()
    # A title is optional. Never infer a listing title or price from unsupported context.
    return title[:200] if title and len(title) >= 4 else None


class _ListingLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str | None]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._href = dict(attrs).get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, _clean_title("".join(self._text))))
            self._href = None
            self._text = []


def extract_alert_listings(message_bytes: bytes) -> list[ImmoweltAlertListing]:
    """Extract only direct offer links from a downloaded EML; deduplicate by offer ID.

    From headers are not authenticated by parsing an EML; the operator must obtain
    messages through their own trusted inbox. This function never fetches links.
    """
    message = BytesParser(policy=policy.default).parsebytes(message_bytes)
    listings: dict[str, ImmoweltAlertListing] = {}
    for part in message.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        if part.get_content_type() not in {"text/plain", "text/html"}:
            continue
        try:
            text = part.get_content()
        except (LookupError, UnicodeError, ValueError):
            continue
        if not isinstance(text, str):
            continue

        links: list[tuple[str, str | None]]
        if part.get_content_type() == "text/html":
            parser = _ListingLinks()
            parser.feed(text)
            links = parser.links + [(url, None) for url in _HTTP_LINK.findall(text)]
        else:
            links = [(url, None) for url in _HTTP_LINK.findall(text)]

        for raw, title in links:
            # A URL in a notification is not proof of a currently active listing.
            # Only output validated canonical pointers; no data enrichment here.
            canonical = canonical_alert_url(raw.rstrip(".,;!?"))
            if canonical is None:
                continue
            listing_id, url = canonical
            old = listings.get(listing_id)
            if old is None or (old.title is None and title):
                listings[listing_id] = ImmoweltAlertListing(listing_id, url, title)
    return list(listings.values())


def extract_alert_files(paths: list[Path]) -> list[ImmoweltAlertListing]:
    """Read bounded local exports and deduplicate across saved-search messages."""
    found: dict[str, ImmoweltAlertListing] = {}
    for path in paths:
        if path.suffix.lower() != ".eml":
            raise ValueError(f"Expected .eml file: {path.name}")
        if not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError(f"Input must be a local EML of at most 8 MiB: {path.name}")
        for listing in extract_alert_listings(path.read_bytes()):
            previous = found.get(listing.source_listing_id)
            if previous is None or (previous.title is None and listing.title):
                found[listing.source_listing_id] = listing
    return list(found.values())
