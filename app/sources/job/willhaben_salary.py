from __future__ import annotations

from typing import Any

import httpx

from app.sources.base import RawJob, SourceBatch, SourceShardSpec
from app.sources.job.detail_salary import parse_salary_detail_html
from app.sources.job.salary_detail_selection import salary_detail_candidates
from app.sources.job.willhaben_jobs import WillhabenJobSource as SearchCardWillhabenJobSource
from app.sources.job.willhaben_jobs import WillhabenSearch


class WillhabenJobSource(SearchCardWillhabenJobSource):
    """Willhaben frontier using full visible detail context for explicit salaries."""

    def __init__(
        self,
        *,
        searches: list[WillhabenSearch] | None = None,
        request_delay_seconds: float = 1.0,
        max_details_per_shard: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # Disable the older narrow snippet enrichment; this adapter replaces it with
        # the shared full-context parser so clauses such as "Bereitschaft zur Überzahlung"
        # remain part of the salary evidence.
        super().__init__(
            searches=searches,
            request_delay_seconds=request_delay_seconds,
            max_details_per_shard=0,
            transport=transport,
        )
        self.salary_details_per_shard = (
            max_details_per_shard
            if max_details_per_shard is not None and max_details_per_shard > 0
            else None
        )

    async def fetch_shard(
        self,
        shard: SourceShardSpec,
        *,
        cursor: dict[str, Any] | None = None,
        reconciliation: bool = False,
    ) -> SourceBatch[RawJob]:
        batch = await super().fetch_shard(
            shard,
            cursor=cursor,
            reconciliation=reconciliation,
        )
        if not batch.items:
            return batch

        candidates = salary_detail_candidates(batch.items)
        selected = (
            candidates[: self.salary_details_per_shard]
            if self.salary_details_per_shard is not None
            else candidates
        )

        details_fetched = 0
        details_failed = 0
        salary_details_found = 0

        if selected:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                transport=self.transport,
                headers={
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                    "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
                    "User-Agent": "WohnWerk/0.3 (+private self-hosted Austrian job search)",
                },
            ) as client:
                for item in selected:
                    try:
                        detail_content = await self._request_text(client, item.url)
                    except httpx.HTTPError as exc:
                        payload = dict(item.raw_payload)
                        payload["detail_enrichment_error"] = f"{type(exc).__name__}: {exc}"
                        item.raw_payload = payload
                        details_failed += 1
                        continue

                    details_fetched += 1
                    parsed = parse_salary_detail_html(detail_content)
                    payload = dict(item.raw_payload)
                    payload["detail_enriched"] = True
                    payload["acquisition_level"] = "search-card+salary-detail"
                    payload["willhaben_detail_salary_found"] = parsed is not None
                    if parsed is not None:
                        item.salary_text = parsed.text
                        salary_details_found += 1
                    item.raw_payload = payload

        diagnostics = dict(batch.next_cursor)
        diagnostics.update(
            {
                "strategy": "first-page-search-card-frontier+accepted-salary-detail",
                "salary_detail_candidates": len(candidates),
                "salary_detail_selected": len(selected),
                "salary_detail_limit": self.salary_details_per_shard,
                "details_fetched": details_fetched,
                "details_failed": details_failed,
                "salary_details_found": salary_details_found,
            }
        )
        batch.next_cursor = diagnostics
        batch.pages_fetched += details_fetched + details_failed
        return batch
