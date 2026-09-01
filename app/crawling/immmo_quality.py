from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CrawlRun, PropertyListing, Source
from app.sources.base import RawProperty, SourceBatch

COVERAGE_POLICY_VERSION = "immmo-identity-churn-2026-09-01-v1"


@dataclass(frozen=True, slots=True)
class ImmmoCoverageDecision:
    coverage_complete: bool
    structural_complete: bool
    synthetic_new: int
    synthetic_new_tolerance: int
    identity_churn_ok: bool


def _cursor_int(cursor: dict, key: str) -> int:
    value = cursor.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def synthetic_new_in_shard(
    session: Session,
    *,
    source: Source,
    run: CrawlRun,
    items: list[RawProperty],
) -> int:
    synthetic_ids = {
        item.source_listing_id
        for item in items
        if (item.raw_payload or {}).get("original_url_missing") is True
    }
    if not synthetic_ids:
        return 0

    return int(
        session.scalar(
            select(func.count())
            .select_from(PropertyListing)
            .where(
                PropertyListing.source_id == source.id,
                PropertyListing.source_listing_id.in_(synthetic_ids),
                PropertyListing.last_seen_crawl_run_id == run.id,
                PropertyListing.first_seen_at >= run.started_at,
                PropertyListing.raw_payload.op("->>")("original_url_missing") == "true",
            )
        )
        or 0
    )


def decide_immmo_coverage(
    batch: SourceBatch[RawProperty],
    *,
    reconciliation: bool,
    synthetic_new: int,
) -> ImmmoCoverageDecision:
    cursor = batch.next_cursor or {}
    cards_seen = _cursor_int(cursor, "discovery_cards_seen")
    cards_parsed = _cursor_int(cursor, "discovery_cards_parsed")
    count_delta = _cursor_int(cursor, "discovery_count_delta")
    count_tolerance = _cursor_int(cursor, "discovery_count_tolerance")

    structural_complete = (
        reconciliation
        and cursor.get("discovery_traversal_complete") is True
        and not batch.result_cap_hit
        and cards_seen > 0
        and cards_seen == cards_parsed
        and count_tolerance > 0
        and abs(count_delta) <= count_tolerance
    )

    synthetic_new_tolerance = max(3, math.ceil(cards_seen * 0.01))
    identity_churn_ok = synthetic_new <= synthetic_new_tolerance

    return ImmmoCoverageDecision(
        coverage_complete=structural_complete and identity_churn_ok,
        structural_complete=structural_complete,
        synthetic_new=synthetic_new,
        synthetic_new_tolerance=synthetic_new_tolerance,
        identity_churn_ok=identity_churn_ok,
    )


def annotate_immmo_coverage_cursor(
    cursor: dict,
    decision: ImmmoCoverageDecision,
) -> dict:
    annotated = dict(cursor)
    annotated["discovery_coverage_policy"] = COVERAGE_POLICY_VERSION
    annotated["discovery_structural_coverage_ok"] = decision.structural_complete
    annotated["discovery_synthetic_new"] = decision.synthetic_new
    annotated["discovery_synthetic_new_tolerance"] = decision.synthetic_new_tolerance
    annotated["discovery_identity_churn_ok"] = decision.identity_churn_ok
    annotated["discovery_legacy_link_quality_ok"] = annotated.get(
        "discovery_link_quality_ok"
    )
    return annotated
