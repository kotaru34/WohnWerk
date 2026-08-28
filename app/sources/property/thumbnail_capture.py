from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from app.property_thumbnail_cache import _LinkedThumbnailParser, _comparison_url
from app.sources.base import RawProperty, SourceBatch, SourceShardSpec
from app.sources.property.immmo_v3 import ImmmoPropertySource as _ImmmoPropertySource
from app.sources.property.sreal_v2 import SRealPropertySource as _SRealPropertySource


class _SearchThumbnailCaptureMixin:
    thumbnail_search_path_marker: str

    def _reset_thumbnail_capture(self) -> None:
        self._captured_thumbnails: dict[str, str] = {}

    async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        response = await super()._get(client, url)  # type: ignore[misc]
        path = urlparse(str(response.url)).path
        if self.thumbnail_search_path_marker not in path:
            return response
        content_type = response.headers.get("content-type", "").casefold()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            return response
        parser = _LinkedThumbnailParser(page_url=str(response.url))
        parser.feed(response.text)
        self._captured_thumbnails.update(parser.images)
        return response

    def _attach_captured_thumbnails(self, items: list[RawProperty]) -> int:
        attached = 0
        for item in items:
            key = _comparison_url(item.url)
            thumbnail_url = self._captured_thumbnails.get(key or "")
            if thumbnail_url is None:
                continue
            payload = dict(item.raw_payload)
            payload["thumbnail_url"] = thumbnail_url
            payload["thumbnail_semantics"] = "search_card_exact_anchor"
            item.raw_payload = payload
            attached += 1
        return attached


class ImmmoThumbnailPropertySource(_SearchThumbnailCaptureMixin, _ImmmoPropertySource):
    """IMMMO v3 plus exact-anchor thumbnail capture from already-fetched search pages."""

    thumbnail_search_path_marker = "/immo/Haus-kaufen/"

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        self._reset_thumbnail_capture()
        batch = await super().fetch_shard(
            shard,
            cursor=cursor,
            reconciliation=reconciliation,
        )
        attached = self._attach_captured_thumbnails(batch.items)
        batch.next_cursor["thumbnail_urls_captured"] = attached
        return batch


class SRealThumbnailPropertySource(_SearchThumbnailCaptureMixin, _SRealPropertySource):
    """s REAL v2 plus exact-anchor thumbnail capture from already-fetched search pages."""

    thumbnail_search_path_marker = "/de/haeuser-kauf/angebot/10"

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawProperty]:
        self._reset_thumbnail_capture()
        batch = await super().fetch_shard(
            shard,
            cursor=cursor,
            reconciliation=reconciliation,
        )
        attached = self._attach_captured_thumbnails(batch.items)
        batch.next_cursor["thumbnail_urls_captured"] = attached
        return batch
