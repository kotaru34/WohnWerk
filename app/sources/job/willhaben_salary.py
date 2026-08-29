from __future__ import annotations

from typing import Any

import httpx

from app.sources.base import RawJob, SourceBatch, SourceShardSpec
from app.sources.job.detail_salary import detail_worthy_title, parse_salary_detail_html
from app.sources.job.willhaben_jobs import WillhabenJobSource as SearchCardWillhabenJobSource
from app.sources.job.willhaben_jobs import WillhabenSearch


class WillhabenJobSource(SearchCardWillhabenJobSource):
    """Willhaben frontier using full visible detail context for explicit salaries."""

    def __init__(
        self,
        *,
        searches: list[WillhabenSearch] | None = None,
        request_delay_seconds: float = 1.0,
        max_details_per_shard: int = 8,
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
        self.salary_details_per_shard = max(0, max_details_per_shard)

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
        if not batch.items or self.salary_details_per_shard <= 0:
            return batch

        details_fetched = 0
        details_failed = 0
        salary_details_found = 0
        budget_used = 0

        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            transport=self.transport,
            headers={
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                "Accept-Language": "de-AT,de;q=0.9,en;q=0.5",
                "User-Agent": "WohnWerk/0.2 (+private self-hosted Austrian job search)",
            },
        ) as client:
            for item in batch.items:
                if budget_used >= self.salary_details_per_shard:
                    break
                if not detail_worthy_title(item.title):
                    continue
                budget_used += 1
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
                "strategy": "first-page-search-card-frontier+bounded-salary-detail",
                "details_fetched": details_fetched,
                "details_failed": details_failed,
                "salary_details_found": salary_details_found,
            }
        )
        batch.next_cursor = diagnostics
        batch.pages_fetched += details_fetched + details_failed
        return batch
