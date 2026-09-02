from __future__ import annotations

import asyncio
import ipaddress
import mimetypes
import os
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, and_, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.candidate_activity import hidden_property_ids
from app.config import get_settings
from app.database import Base
from app.jobs.candidate_profile_store import get_seed_profile
from app.models import ListingStatus, Property, PropertyListing
from app.property_visibility import product_visible_property_condition

IMAGE_META_KEYS = {"og:image", "twitter:image", "twitter:image:src"}
CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/gif": ".gif",
}
MAX_LISTING_PAGES_PER_PROPERTY = 3


class PropertyImage(Base):
    __tablename__ = "property_images"
    __table_args__ = (Index("ix_property_images_retry", "status", "retry_after"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    property_listing_id: Mapped[int | None] = mapped_column(
        ForeignKey("property_listings.id", ondelete="SET NULL"), index=True
    )
    source_image_url: Mapped[str | None] = mapped_column(Text)
    local_filename: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True, slots=True)
class ImageCacheResult:
    attempted: int = 0
    cached: int = 0
    missing: int = 0
    failed: int = 0
    skipped: int = 0


class _ImageMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.image_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.image_url is not None:
            return
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag.casefold() == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").casefold()
            content = attributes.get("content", "").strip()
            if key in IMAGE_META_KEYS and content:
                self.image_url = content
        elif tag.casefold() == "link":
            rel = attributes.get("rel", "").casefold().split()
            href = attributes.get("href", "").strip()
            if "image_src" in rel and href:
                self.image_url = href


def _payload_image_url(payload: dict | None) -> str | None:
    for key in ("primary_image_url", "image_url", "thumbnail_url"):
        value = (payload or {}).get(key)
        if isinstance(value, str):
            safe = _safe_http_url(value)
            if safe:
                return safe
    return None


def _safe_http_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not hostname:
        return None
    if hostname == "localhost" or hostname.endswith(".local"):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return None
    return value


def cached_image_urls(session: Session, property_ids: set[int]) -> dict[int, str]:
    if not property_ids:
        return {}
    rows = session.execute(
        select(PropertyImage.property_id, PropertyImage.local_filename).where(
            PropertyImage.property_id.in_(property_ids),
            PropertyImage.status == "cached",
            PropertyImage.local_filename.is_not(None),
        )
    )
    return {
        int(property_id): f"/media/properties/{int(property_id)}"
        for property_id, local_filename in rows
        if local_filename
    }


def local_image_path(session: Session, property_id: int) -> Path | None:
    row = session.scalar(
        select(PropertyImage).where(
            PropertyImage.property_id == property_id,
            PropertyImage.status == "cached",
            PropertyImage.local_filename.is_not(None),
        )
    )
    if row is None or not row.local_filename:
        return None
    settings = get_settings()
    root = Path(settings.property_image_dir).resolve()
    candidate = (root / row.local_filename).resolve()
    if candidate.parent != root or not candidate.is_file():
        return None
    return candidate


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


def _candidate_property_ids(session: Session, *, limit: int) -> list[int]:
    profile = get_seed_profile(session)
    hidden = hidden_property_ids(session, profile.id) if profile is not None else set()
    now = datetime.now(UTC)

    retryable = or_(
        PropertyImage.id.is_(None),
        and_(
            PropertyImage.status != "cached",
            or_(
                PropertyImage.retry_after.is_(None),
                PropertyImage.retry_after <= now,
            ),
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
        .limit(limit * 4)
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


async def _discover_image_url(
    client: httpx.AsyncClient,
    listing: PropertyListing,
) -> str | None:
    known = _payload_image_url(listing.raw_payload)
    if known:
        return known

    page_url = _safe_http_url(listing.url)
    if page_url is None or "/wohnwerk-fallback/" in page_url:
        return None
    response = await client.get(page_url)
    response.raise_for_status()
    if _safe_http_url(str(response.url)) is None:
        return None
    content_type = response.headers.get("content-type", "").casefold()
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        return None
    parser = _ImageMetaParser()
    parser.feed(response.text)
    if not parser.image_url:
        return None
    return _safe_http_url(urljoin(str(response.url), parser.image_url))


async def _download_image(
    client: httpx.AsyncClient,
    image_url: str,
    *,
    property_id: int,
) -> str:
    settings = get_settings()
    if _safe_http_url(image_url) is None:
        raise ValueError("unsafe image URL")
    async with client.stream("GET", image_url) as response:
        response.raise_for_status()
        if _safe_http_url(str(response.url)) is None:
            raise ValueError("unsafe redirected image URL")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
        extension = CONTENT_TYPE_EXTENSIONS.get(content_type)
        if extension is None:
            guessed = mimetypes.guess_extension(content_type) if content_type.startswith("image/") else None
            if guessed not in {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}:
                raise ValueError(f"unsupported image content type: {content_type or 'missing'}")
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
    filename = f"{property_id}{extension}"
    target = root / filename
    temporary = root / f".{filename}.{os.getpid()}.tmp"
    temporary.write_bytes(b"".join(chunks))
    os.replace(temporary, target)
    return filename


async def cache_missing_property_images(
    session: Session,
    *,
    limit: int | None = None,
    delay_seconds: float | None = None,
) -> ImageCacheResult:
    settings = get_settings()
    limit = max(1, limit or settings.property_image_worker_limit)
    delay = max(
        0.0,
        delay_seconds if delay_seconds is not None else settings.property_image_worker_delay_seconds,
    )
    property_ids = _candidate_property_ids(session, limit=limit)

    attempted = cached = missing = failed = skipped = 0
    headers = {
        "User-Agent": "WohnWerk/0.1 (+private self-hosted Austrian property search)",
        "Accept": "text/html,image/avif,image/webp,image/*,*/*;q=0.8",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
    }
    async with httpx.AsyncClient(
        headers=headers,
        timeout=settings.property_image_timeout_seconds,
        follow_redirects=True,
    ) as client:
        for property_id in property_ids:
            listings = sorted(_active_listings(session, property_id), key=_listing_priority)
            listings = listings[:MAX_LISTING_PAGES_PER_PROPERTY]
            if not listings:
                skipped += 1
                continue

            row = _cache_row(session, property_id)
            now = datetime.now(UTC)
            row.attempts += 1
            row.last_attempt_at = now
            row.updated_at = now
            attempted += 1

            try:
                image_url = None
                selected_listing = None
                for listing in listings:
                    image_url = await _discover_image_url(client, listing)
                    if image_url:
                        selected_listing = listing
                        break
                    if delay:
                        await asyncio.sleep(delay * random.uniform(0.8, 1.2))

                if image_url is None or selected_listing is None:
                    row.status = "missing"
                    row.retry_after = now + timedelta(days=7)
                    row.last_error = None
                    missing += 1
                    session.commit()
                    continue

                if delay:
                    await asyncio.sleep(delay * random.uniform(0.8, 1.2))
                filename = await _download_image(client, image_url, property_id=property_id)
                row.property_listing_id = selected_listing.id
                row.source_image_url = image_url
                row.local_filename = filename
                row.status = "cached"
                row.retry_after = None
                row.fetched_at = datetime.now(UTC)
                row.last_error = None
                cached += 1
            except (httpx.HTTPError, OSError, ValueError) as exc:
                row.status = "failed"
                row.retry_after = now + timedelta(days=1)
                row.last_error = f"{type(exc).__name__}: {exc}"[:1000]
                failed += 1
            session.commit()

    return ImageCacheResult(
        attempted=attempted,
        cached=cached,
        missing=missing,
        failed=failed,
        skipped=skipped,
    )
