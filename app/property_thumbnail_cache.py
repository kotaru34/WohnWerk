from __future__ import annotations

import asyncio
import mimetypes
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.candidate_activity import hidden_property_ids
from app.config import get_settings
from app.jobs.candidate_profile_store import get_seed_profile
from app.models import ListingStatus, Property, PropertyListing
from app.property_images import PropertyImage, _safe_http_url
from app.property_visibility import product_visible_property_condition

CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/gif": ".gif",
}
DISCOVERY_HOSTS = {"immmo.at", "www.immmo.at", "sreal.at", "www.sreal.at"}
TRACKING_QUERY_KEYS = {"fbclid", "gclid"}
MAX_DISCOVERY_PAGES_PER_PROPERTY = 2
THUMBNAIL_TARGET_WIDTH_PX = 720.0
THUMBNAIL_TARGET_DENSITY = 1.5


@dataclass(frozen=True, slots=True)
class ThumbnailCacheResult:
    attempted: int = 0
    cached: int = 0
    missing: int = 0
    failed: int = 0
    skipped: int = 0
    known_urls: int = 0
    discovered_urls: int = 0
    discovery_pages: int = 0
    discovery_failed: int = 0


@dataclass(frozen=True, slots=True)
class _ImagePlan:
    property_id: int
    listing_id: int
    image_url: str


@dataclass(frozen=True, slots=True)
class _DiscoveryTarget:
    property_id: int
    listing_id: int
    listing_url: str


def _safe_discovery_url(value: str | None) -> str | None:
    safe = _safe_http_url(value)
    if safe is None:
        return None
    host = (urlparse(safe).hostname or "").casefold()
    return safe if host in DISCOVERY_HOSTS else None


def _comparison_url(value: str, *, base_url: str | None = None) -> str | None:
    absolute = urljoin(base_url or value, value)
    safe = _safe_http_url(absolute)
    if safe is None:
        return None
    parsed = urlparse(safe)
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in TRACKING_QUERY_KEYS
        and not key.casefold().startswith("utm_")
    ]
    return urlunparse(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path.rstrip("/") or "/",
            "",
            urlencode(query, doseq=True),
            "",
        )
    )


def _balanced_srcset_url(value: str) -> str | None:
    """Choose a moderate preview candidate instead of the smallest or hero-sized image."""
    widths: list[tuple[float, float, str]] = []
    densities: list[tuple[float, float, str]] = []
    undescribed: list[str] = []

    for raw in value.split(","):
        parts = raw.strip().split()
        if not parts:
            continue
        url = parts[0]
        if len(parts) == 1:
            undescribed.append(url)
            continue

        descriptor = parts[-1].casefold()
        try:
            if descriptor.endswith("w"):
                width = float(descriptor[:-1])
                widths.append((abs(width - THUMBNAIL_TARGET_WIDTH_PX), width, url))
            elif descriptor.endswith("x"):
                density = float(descriptor[:-1])
                densities.append(
                    (abs(density - THUMBNAIL_TARGET_DENSITY), -density, url)
                )
            else:
                undescribed.append(url)
        except ValueError:
            undescribed.append(url)

    if widths:
        # On an exact tie prefer the smaller transfer.
        return min(widths, key=lambda item: (item[0], item[1]))[2]
    if densities:
        # On an exact tie prefer the sharper density (e.g. 2x over 1x around 1.5x).
        return min(densities, key=lambda item: (item[0], item[1]))[2]
    return undescribed[0] if undescribed else None


def _image_attr_candidate(attributes: dict[str, str]) -> str | None:
    for key in ("data-srcset", "srcset"):
        value = attributes.get(key, "").strip()
        if value:
            candidate = _balanced_srcset_url(value)
            if candidate:
                return candidate
    for key in ("data-src", "data-lazy-src", "data-original", "src"):
        value = attributes.get(key, "").strip()
        if value and not value.casefold().startswith("data:"):
            return value
    return None


class _LinkedThumbnailParser(HTMLParser):
    """Map an exact listing anchor to a balanced source-backed preview inside it."""

    def __init__(self, *, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.images: dict[str, str] = {}
        self._anchors: list[tuple[str, str | None]] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth += 1
            return
        if self._hidden_depth:
            return
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag == "a":
            self._anchors.append((attributes.get("href", "").strip(), None))
        elif tag == "img" and self._anchors:
            href, image = self._anchors[-1]
            if image is None and (candidate := _image_attr_candidate(attributes)):
                self._anchors[-1] = (href, candidate)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "img":
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "template"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)
            return
        if self._hidden_depth or tag != "a" or not self._anchors:
            return
        href, image = self._anchors.pop()
        if not href or not image:
            return
        listing_key = _comparison_url(href, base_url=self.page_url)
        image_url = _safe_http_url(urljoin(self.page_url, image))
        if listing_key and image_url:
            self.images.setdefault(listing_key, image_url)


def _payload_image_url(payload: dict | None) -> str | None:
    # Prefer card thumbnails over large detail-page hero images.
    for key in ("thumbnail_url", "primary_image_url", "image_url"):
        value = (payload or {}).get(key)
        if isinstance(value, str) and (safe := _safe_http_url(value)):
            return safe
    return None


def _cache_row(session: Session, property_id: int) -> PropertyImage:
    row = session.scalar(select(PropertyImage).where(PropertyImage.property_id == property_id))
    if row is not None:
        return row
    now = datetime.now(UTC)
    row = PropertyImage(
        property_id=property_id,
        status="pending",
        attempts=0,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return row


def reset_non_cached_image_retries(session: Session) -> int:
    result = session.execute(
        update(PropertyImage)
        .where(PropertyImage.status != "cached")
        .values(status="pending", retry_after=None, last_error=None)
    )
    session.commit()
    return int(result.rowcount or 0)


def _candidate_property_ids(session: Session, *, limit: int) -> list[int]:
    profile = get_seed_profile(session)
    hidden = hidden_property_ids(session, profile.id) if profile is not None else set()
    now = datetime.now(UTC)
    retryable = or_(
        PropertyImage.id.is_(None),
        and_(
            PropertyImage.status != "cached",
            or_(PropertyImage.retry_after.is_(None), PropertyImage.retry_after <= now),
        ),
    )
    stmt = (
        select(Property.id)
        .outerjoin(PropertyImage, PropertyImage.property_id == Property.id)
        .where(
            Property.status == ListingStatus.ACTIVE,
            product_visible_property_condition(),
            retryable,
        )
        .order_by(Property.first_seen_at.desc(), Property.id.desc())
        .limit(limit * 3)
    )
    ids = [int(value) for value in session.scalars(stmt)]
    if hidden:
        ids = [value for value in ids if value not in hidden]
    return ids[:limit]


def _active_listings(session: Session, property_id: int) -> list[PropertyListing]:
    return list(
        session.scalars(
            select(PropertyListing)
            .where(
                PropertyListing.property_id == property_id,
                PropertyListing.status == ListingStatus.ACTIVE,
            )
            .order_by(PropertyListing.id)
        )
    )


def _listing_priority(listing: PropertyListing) -> tuple[int, int]:
    payload = listing.raw_payload or {}
    accepted = payload.get("product_visible") is True
    known_image = _payload_image_url(payload) is not None
    return (0 if accepted and known_image else 1 if known_image else 2 if accepted else 3, listing.id)


def _listing_discovery_url(listing: PropertyListing) -> str | None:
    value = (listing.raw_payload or {}).get("discovery_url")
    return _safe_discovery_url(value if isinstance(value, str) else None)


async def _scan_discovery_page(
    client: httpx.AsyncClient,
    page_url: str,
    semaphore: asyncio.Semaphore,
) -> tuple[str, dict[str, str], str | None]:
    try:
        async with semaphore:
            response = await client.get(page_url)
        response.raise_for_status()
        final_url = _safe_discovery_url(str(response.url))
        if final_url is None:
            raise ValueError("discovery page redirected off source")
        content_type = response.headers.get("content-type", "").casefold()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            raise ValueError("discovery page is not HTML")
        parser = _LinkedThumbnailParser(page_url=final_url)
        parser.feed(response.text)
        return page_url, parser.images, None
    except (httpx.HTTPError, ValueError) as exc:
        return page_url, {}, f"{type(exc).__name__}: {exc}"[:500]


async def _download_image(
    client: httpx.AsyncClient,
    plan: _ImagePlan,
    semaphore: asyncio.Semaphore,
    delay_seconds: float,
) -> tuple[int, str | None, str | None]:
    settings = get_settings()
    try:
        async with semaphore:
            if delay_seconds:
                await asyncio.sleep(delay_seconds)
            async with client.stream("GET", plan.image_url) as response:
                response.raise_for_status()
                if _safe_http_url(str(response.url)) is None:
                    raise ValueError("unsafe redirected image URL")
                content_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
                )
                extension = CONTENT_TYPE_EXTENSIONS.get(content_type)
                if extension is None:
                    guessed = (
                        mimetypes.guess_extension(content_type)
                        if content_type.startswith("image/")
                        else None
                    )
                    if guessed not in {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}:
                        raise ValueError(
                            f"unsupported image content type: {content_type or 'missing'}"
                        )
                    extension = ".jpg" if guessed == ".jpeg" else guessed

                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > settings.property_image_max_bytes:
                        raise ValueError("image exceeds configured byte limit")
                    chunks.append(chunk)
                if total < 256:
                    raise ValueError("image response is unexpectedly small")

        root = Path(settings.property_image_dir)
        root.mkdir(parents=True, exist_ok=True)
        filename = f"{plan.property_id}{extension}"
        target = root / filename
        temporary = root / f".{filename}.{os.getpid()}.tmp"
        temporary.write_bytes(b"".join(chunks))
        os.replace(temporary, target)
        return plan.property_id, filename, None
    except (httpx.HTTPError, OSError, ValueError) as exc:
        return plan.property_id, None, f"{type(exc).__name__}: {exc}"[:1000]


async def cache_property_thumbnails(
    session: Session,
    *,
    limit: int | None = None,
    delay_seconds: float | None = None,
) -> ThumbnailCacheResult:
    """Cache thumbnails from known URLs or batched source search pages; never open details."""
    settings = get_settings()
    limit = max(1, limit or settings.property_image_worker_limit)
    delay = max(0.0, delay_seconds or 0.0)
    property_ids = _candidate_property_ids(session, limit=limit)

    rows: dict[int, PropertyImage] = {}
    plans: dict[int, _ImagePlan] = {}
    discovery_targets: dict[str, list[_DiscoveryTarget]] = {}
    property_pages: dict[int, set[str]] = {}
    skipped = known_urls = 0
    now = datetime.now(UTC)

    for property_id in property_ids:
        listings = sorted(_active_listings(session, property_id), key=_listing_priority)
        if not listings:
            skipped += 1
            continue
        row = _cache_row(session, property_id)
        row.attempts += 1
        row.last_attempt_at = now
        row.updated_at = now
        rows[property_id] = row

        for listing in listings:
            if image_url := _payload_image_url(listing.raw_payload):
                plans[property_id] = _ImagePlan(property_id, listing.id, image_url)
                known_urls += 1
                break
        if property_id in plans:
            continue

        pages: set[str] = set()
        for listing in listings:
            page_url = _listing_discovery_url(listing)
            if page_url is None or page_url in pages:
                continue
            pages.add(page_url)
            property_pages.setdefault(property_id, set()).add(page_url)
            discovery_targets.setdefault(page_url, []).append(
                _DiscoveryTarget(property_id, listing.id, listing.url)
            )
            if len(pages) >= MAX_DISCOVERY_PAGES_PER_PROPERTY:
                break

    headers = {
        "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian property search)",
        "Accept": "text/html,image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
    }
    discovered_urls = discovery_failed = 0
    discovery_success: set[int] = set()
    discovery_errors: dict[int, str] = {}

    async with httpx.AsyncClient(
        headers=headers,
        timeout=settings.property_image_timeout_seconds,
        follow_redirects=True,
    ) as client:
        page_semaphore = asyncio.Semaphore(max(1, settings.property_image_discovery_concurrency))
        page_results = await asyncio.gather(
            *(
                _scan_discovery_page(client, page_url, page_semaphore)
                for page_url in discovery_targets
            )
        )
        for page_url, images, error in page_results:
            targets = discovery_targets[page_url]
            if error is not None:
                discovery_failed += 1
                for target in targets:
                    discovery_errors.setdefault(target.property_id, error)
                continue
            for target in targets:
                discovery_success.add(target.property_id)
                if target.property_id in plans:
                    continue
                key = _comparison_url(target.listing_url)
                image_url = images.get(key or "")
                if image_url is None:
                    continue
                listing = session.get(PropertyListing, target.listing_id)
                if listing is not None:
                    payload = dict(listing.raw_payload or {})
                    payload["thumbnail_url"] = image_url
                    payload["thumbnail_semantics"] = "search_card_exact_anchor"
                    listing.raw_payload = payload
                plans[target.property_id] = _ImagePlan(
                    target.property_id, target.listing_id, image_url
                )
                discovered_urls += 1

        download_semaphore = asyncio.Semaphore(max(1, settings.property_image_worker_concurrency))
        download_results = await asyncio.gather(
            *(
                _download_image(client, plan, download_semaphore, delay)
                for plan in plans.values()
            )
        )

    download_by_property = {
        property_id: (filename, error)
        for property_id, filename, error in download_results
    }
    cached = missing = failed = 0
    finished_at = datetime.now(UTC)

    for property_id, row in rows.items():
        plan = plans.get(property_id)
        row.updated_at = finished_at
        if plan is None:
            row.local_filename = None
            row.source_image_url = None
            if property_id in discovery_success or not property_pages.get(property_id):
                row.status = "missing"
                row.retry_after = finished_at + timedelta(days=1)
                row.last_error = None
                missing += 1
            else:
                row.status = "failed"
                row.retry_after = finished_at + timedelta(hours=6)
                row.last_error = discovery_errors.get(property_id, "discovery page failed")
                failed += 1
            continue

        filename, error = download_by_property[property_id]
        row.property_listing_id = plan.listing_id
        row.source_image_url = plan.image_url
        if filename is not None:
            row.local_filename = filename
            row.status = "cached"
            row.retry_after = None
            row.fetched_at = finished_at
            row.last_error = None
            cached += 1
        else:
            row.status = "failed"
            row.retry_after = finished_at + timedelta(hours=6)
            row.last_error = error
            failed += 1

    session.commit()
    return ThumbnailCacheResult(
        attempted=len(rows),
        cached=cached,
        missing=missing,
        failed=failed,
        skipped=skipped,
        known_urls=known_urls,
        discovered_urls=discovered_urls,
        discovery_pages=len(discovery_targets),
        discovery_failed=discovery_failed,
    )
