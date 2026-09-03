from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crawling.challenge import (
    ChallengeHandler,
    ChallengeRequest,
    DeferredChallengeHandler,
)
from app.crawling.coverage import (
    RUN_STATUS_PAUSED,
    SHARD_STATUS_SKIPPED,
    CoverageSummary,
    checkpoint_paused_run,
    create_run,
    finalize_run,
    reconcile_missing_listings,
)
from app.crawling.immmo_quality import (
    annotate_immmo_coverage_cursor,
    decide_immmo_coverage,
    synthetic_new_in_shard,
)
from app.crawling.shards import sync_source_shards
from app.ingestion.immmo_continuity import reconcile_immmo_continuity
from app.ingestion.properties import ingest_properties
from app.live_events import queue_live_event
from app.models import CoverageStatus, CrawlMode, CrawlRun, CrawlShardRun, RunStatus, Source, SourceShard
from app.property_acquisition import annotate_property_items_by_budget
from app.property_liveness import prepare_immmo_item_liveness
from app.sources.base import (
    PropertySource,
    RawProperty,
    SourceChallenge,
    SourceFetchError,
)

DEFAULT_CHALLENGE_STATE_ROOT = Path("/var/lib/wohnwerk/challenge-state")


async def _annotate_visibility_with_cursor(
    session: Session,
    source: Source,
    items: list[RawProperty],
    cursor: dict,
) -> dict:
    liveness = await prepare_immmo_item_liveness(session, source, items)
    counts = annotate_property_items_by_budget(items)
    next_cursor = dict(cursor)
    next_cursor["product_visible"] = sum(
        (item.raw_payload or {}).get("product_visible") is True for item in items
    )
    next_cursor["product_price_accepted"] = counts["accepted"]
    next_cursor["product_price_unknown"] = counts["price_unknown"]
    next_cursor["product_price_below_min"] = counts["price_below_min"]
    next_cursor["product_price_above_max"] = counts["price_above_max"]
    if source.name == "immmo.at":
        next_cursor["source_liveness_attempted"] = liveness.attempted
        next_cursor["source_liveness_live"] = liveness.live
        next_cursor["source_liveness_dead"] = liveness.dead
        next_cursor["source_liveness_unknown"] = liveness.unknown
    return next_cursor


def _ordered_shards(shards: list[SourceShard], *, reconciliation: bool) -> list[SourceShard]:
    if reconciliation:
        return sorted(shards, key=lambda item: (item.priority, item.id))

    epoch = datetime.min.replace(tzinfo=UTC)
    return sorted(
        shards,
        key=lambda item: (
            item.priority,
            item.last_success_at is not None,
            item.last_success_at or epoch,
            item.id,
        ),
    )


def _persist_shard_order(run: CrawlRun, ordered_shards: list[SourceShard]) -> None:
    metadata = dict(run.run_metadata or {})
    metadata["shard_order"] = [
        {"id": shard.id, "key": shard.key, "priority": shard.priority}
        for shard in ordered_shards
    ]
    run.run_metadata = metadata


def _restore_shard_order(run: CrawlRun, shards: list[SourceShard]) -> list[SourceShard]:
    metadata = dict(run.run_metadata or {})
    persisted = metadata.get("shard_order")
    by_id = {shard.id: shard for shard in shards}
    if not isinstance(persisted, list):
        raise RuntimeError(f"Paused crawl run {run.id} has no persisted fair shard order")

    ordered: list[SourceShard] = []
    for item in persisted:
        if not isinstance(item, dict):
            continue
        try:
            shard_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        shard = by_id.get(shard_id)
        if shard is not None:
            ordered.append(shard)
    if len(ordered) != len(persisted):
        raise RuntimeError(f"Paused crawl run {run.id} shard set changed while it was paused")
    return ordered


def _mark_unattempted_after_source_halt(
    session: Session,
    *,
    run_id: int,
    source_name: str,
    failed_spec_key: str,
    remaining_shards: list[SourceShard],
    reason: str,
) -> None:
    """Mark untouched work as skipped without inflating actual failure telemetry."""
    now = datetime.now(UTC)
    for shard in remaining_shards:
        shard_run = session.scalar(
            select(CrawlShardRun).where(
                CrawlShardRun.crawl_run_id == run_id,
                CrawlShardRun.shard_id == shard.id,
            )
        )
        if shard_run is None or shard_run.status != RunStatus.RUNNING:
            continue
        shard_run.status = SHARD_STATUS_SKIPPED
        shard_run.finished_at = now
        shard_run.coverage_complete = False
        shard_run.error = (
            "SourceSkipped: not attempted after source-wide halt at "
            f"{source_name}/{failed_spec_key}: {reason}"
        )


def _source_halt_reason(exc: Exception) -> str | None:
    if isinstance(exc, SourceFetchError) and exc.halt_source:
        return str(exc)
    return None


def _active_challenge(run: CrawlRun) -> dict[str, Any] | None:
    value = dict(run.run_metadata or {}).get("active_challenge")
    return value if isinstance(value, dict) else None


def _challenge_request_from_payload(payload: dict[str, Any]) -> ChallengeRequest:
    return ChallengeRequest(
        source=str(payload["source"]),
        run_id=int(payload["run_id"]),
        shard_id=int(payload["shard_id"]),
        shard_key=str(payload["shard_key"]),
        shard_params=dict(payload.get("shard_params") or {}),
        mode=str(payload["mode"]),
        reason=str(payload["reason"]),
        challenge=dict(payload.get("challenge") or {}),
        resume_cursor=dict(payload.get("resume_cursor") or {}),
        handoff_state=dict(payload.get("handoff_state") or {}),
    )


def _record_challenge_result(
    run: CrawlRun,
    request: ChallengeRequest,
    *,
    action: str,
    message: str | None,
) -> None:
    metadata = dict(run.run_metadata or {})
    history = list(metadata.get("challenge_history") or [])
    history.append(
        {
            "at": datetime.now(UTC).isoformat(),
            "shard_id": request.shard_id,
            "shard_key": request.shard_key,
            "resume_page": request.resume_cursor.get("resume_page"),
            "action": action,
            "message": message,
        }
    )
    metadata["challenge_history"] = history[-100:]
    if action == "resolved":
        metadata.pop("active_challenge", None)
    run.run_metadata = metadata


async def _ingest_partial_fetch(
    session: Session,
    *,
    source_id: int,
    run_id: int,
    exc: SourceFetchError,
) -> tuple[int, int, int, dict[str, Any]]:
    partial_new = 0
    partial_updated = 0
    partial_seen = 0
    partial_cursor = dict(exc.next_cursor)
    if exc.partial_items:
        partial_source = session.get(Source, source_id)
        partial_run = session.get(CrawlRun, run_id)
        if partial_source is None or partial_run is None:
            raise RuntimeError("Could not reload partial property-run state") from exc
        partial_items = cast(list[RawProperty], exc.partial_items)
        partial_cursor = await _annotate_visibility_with_cursor(
            session,
            partial_source,
            partial_items,
            partial_cursor,
        )
        partial_seen = len(partial_items)
        partial_new, partial_updated = ingest_properties(
            session,
            source=partial_source,
            run=partial_run,
            items=partial_items,
        )
    return partial_seen, partial_new, partial_updated, partial_cursor


def _apply_attempt_metrics(
    shard_run: CrawlShardRun,
    *,
    pages_fetched: int,
    items_seen: int,
    items_new: int,
    items_updated: int,
    source_reported_count: int | None,
    next_cursor: dict[str, Any],
) -> None:
    shard_run.pages_fetched += pages_fetched
    shard_run.items_seen += items_seen
    shard_run.items_new += items_new
    shard_run.items_updated += items_updated
    if source_reported_count is not None:
        shard_run.source_reported_count = source_reported_count
    shard_run.next_cursor = dict(next_cursor)


def _queue_house_refresh(session: Session, source: Source, run: CrawlRun, summary: CoverageSummary) -> None:
    queue_live_event(
        session,
        topic="houses",
        kind="catalog_refresh",
        payload={
            "source": source.name,
            "run_id": run.id,
            "mode": str(run.mode),
            "status": str(summary.run_status),
            "coverage": str(summary.coverage_status),
            "failed": summary.shards_failed,
            "skipped": summary.shards_skipped,
            "paused": summary.shards_paused,
        },
    )


async def run_property_source(
    session: Session,
    *,
    source: Source,
    adapter: PropertySource,
    reconciliation: bool = False,
    challenge_handler: ChallengeHandler | None = None,
    challenge_state_root: Path = DEFAULT_CHALLENGE_STATE_ROOT,
    resume_run_id: int | None = None,
    max_challenge_handoffs_per_run: int = 8,
) -> tuple[CrawlRun, CoverageSummary]:
    """Run property shards sequentially with resumable challenge handoff.

    Incremental runs preserve fair never/least-recently-successful scheduling. The exact
    order is frozen into run metadata so a challenge resume continues the same run rather
    than recomputing fairness and starting over. An access challenge checkpoints the exact
    shard/page cursor and browser handoff state before control is offered to an external,
    user-provided handler. Degraded/partial work is never granted reconciliation authority.
    """
    specs = adapter.default_shards()
    shards = sync_source_shards(session, source, specs)
    specs_by_key = {spec.key: spec for spec in specs}
    mode = CrawlMode.RECONCILIATION if reconciliation else CrawlMode.INCREMENTAL
    source_id = source.id

    if resume_run_id is None:
        run = create_run(session, source, mode)
        ordered_shards = _ordered_shards(shards, reconciliation=reconciliation)
        _persist_shard_order(run, ordered_shards)
        session.commit()
    else:
        run = session.get(CrawlRun, resume_run_id)
        if run is None or run.source_id != source_id:
            raise RuntimeError(f"Cannot resume unknown run {resume_run_id} for {source.name}")
        if run.status != RUN_STATUS_PAUSED or run.finished_at is not None:
            raise RuntimeError(f"Run {run.id} is not an unfinished paused run")
        if run.mode != mode:
            raise RuntimeError(
                f"Run {run.id} mode {run.mode!r} does not match requested mode {mode!r}"
            )
        ordered_shards = _restore_shard_order(run, shards)

    run_id = run.id
    handler = challenge_handler or DeferredChallengeHandler()
    handoff_count = len(list((run.run_metadata or {}).get("challenge_history") or []))

    for index, shard in enumerate(ordered_shards):
        spec = specs_by_key.get(shard.key)
        if spec is None:
            raise RuntimeError(f"Missing current shard spec for {source.name}/{shard.key}")
        shard_run = session.scalar(
            select(CrawlShardRun).where(
                CrawlShardRun.crawl_run_id == run_id,
                CrawlShardRun.shard_id == shard.id,
            )
        )
        if shard_run is None:
            raise RuntimeError(f"Missing crawl shard run for {source.name}/{shard.key}")
        if shard_run.status in {RunStatus.SUCCESS, RunStatus.FAILED, SHARD_STATUS_SKIPPED}:
            continue

        shard_id = shard.id
        shard_run_id = shard_run.id
        resume_cursor: dict[str, Any] | None = None

        if shard_run.status == RUN_STATUS_PAUSED:
            payload = _active_challenge(run)
            if payload is None or int(payload.get("shard_id") or -1) != shard_id:
                raise RuntimeError(f"Paused run {run_id} lost active challenge metadata")
            request = _challenge_request_from_payload(payload)
            result = await handler.handle(request)
            _record_challenge_result(
                run,
                request,
                action=result.action,
                message=result.message,
            )
            if result.action == "defer":
                metadata = dict(run.run_metadata or {})
                metadata["active_challenge"] = request.to_payload()
                run.run_metadata = metadata
                summary = checkpoint_paused_run(session, run)
                current_source = session.get(Source, source_id)
                if current_source is not None:
                    _queue_house_refresh(session, current_source, run, summary)
                    session.commit()
                return run, summary
            if result.action == "abort":
                shard_run.status = RunStatus.FAILED
                shard_run.finished_at = datetime.now(UTC)
                shard_run.coverage_complete = False
                shard_run.error = result.message or "user challenge handler aborted"
                shard.consecutive_failures += 1
                _mark_unattempted_after_source_halt(
                    session,
                    run_id=run_id,
                    source_name=source.name,
                    failed_spec_key=spec.key,
                    remaining_shards=ordered_shards[index + 1 :],
                    reason=shard_run.error,
                )
                session.commit()
                break
            if result.retry_after_seconds:
                await asyncio.sleep(result.retry_after_seconds)
            await adapter.restore_challenge_handoff(request.handoff_state)
            shard_run.status = RunStatus.RUNNING
            shard_run.finished_at = None
            shard_run.error = None
            run.status = RunStatus.RUNNING
            run.coverage_status = CoverageStatus.UNKNOWN
            session.commit()
            resume_cursor = request.resume_cursor

        while True:
            halt_reason: str | None = None
            try:
                batch = await adapter.fetch_shard(
                    spec,
                    cursor=resume_cursor if resume_cursor is not None else shard.cursor,
                    reconciliation=reconciliation,
                )
                current_source = session.get(Source, source_id)
                current_run = session.get(CrawlRun, run_id)
                current_shard_run = session.get(CrawlShardRun, shard_run_id)
                current_shard = session.get(SourceShard, shard_id)
                if (
                    current_source is None
                    or current_run is None
                    or current_shard_run is None
                    or current_shard is None
                ):
                    raise RuntimeError(f"Could not reload run state for {source.name}/{spec.key}")

                next_cursor = await _annotate_visibility_with_cursor(
                    session,
                    current_source,
                    batch.items,
                    batch.next_cursor,
                )
                new_count, updated_count = ingest_properties(
                    session,
                    source=current_source,
                    run=current_run,
                    items=batch.items,
                )

                coverage_complete = batch.coverage_complete
                if current_source.name == "immmo.at":
                    synthetic_new = synthetic_new_in_shard(
                        session,
                        source=current_source,
                        run=current_run,
                        items=batch.items,
                    )
                    decision = decide_immmo_coverage(
                        batch,
                        reconciliation=reconciliation,
                        synthetic_new=synthetic_new,
                    )
                    coverage_complete = decision.coverage_complete
                    next_cursor = annotate_immmo_coverage_cursor(next_cursor, decision)

                now = datetime.now(UTC)
                _apply_attempt_metrics(
                    current_shard_run,
                    pages_fetched=batch.pages_fetched,
                    items_seen=len(batch.items),
                    items_new=new_count,
                    items_updated=updated_count,
                    source_reported_count=batch.source_reported_count,
                    next_cursor=next_cursor,
                )
                current_shard_run.status = RunStatus.SUCCESS
                current_shard_run.finished_at = now
                current_shard_run.result_cap_hit = batch.result_cap_hit
                current_shard_run.coverage_complete = coverage_complete
                current_shard_run.error = None

                current_shard.cursor = next_cursor
                current_shard.last_item_count = current_shard_run.items_seen
                current_shard.last_success_at = now
                current_shard.consecutive_failures = 0
                if reconciliation and coverage_complete and not batch.result_cap_hit:
                    current_shard.last_full_scan_at = now
                session.commit()
                resume_cursor = None
                break
            except SourceChallenge as exc:
                session.rollback()
                partial_seen, partial_new, partial_updated, partial_cursor = await _ingest_partial_fetch(
                    session,
                    source_id=source_id,
                    run_id=run_id,
                    exc=exc,
                )
                paused_shard_run = session.get(CrawlShardRun, shard_run_id)
                paused_shard = session.get(SourceShard, shard_id)
                paused_run = session.get(CrawlRun, run_id)
                paused_source = session.get(Source, source_id)
                if (
                    paused_shard_run is None
                    or paused_shard is None
                    or paused_run is None
                    or paused_source is None
                ):
                    raise RuntimeError(
                        f"Could not reload challenged run state for {source.name}/{spec.key}"
                    ) from exc

                _apply_attempt_metrics(
                    paused_shard_run,
                    pages_fetched=exc.pages_fetched,
                    items_seen=partial_seen,
                    items_new=partial_new,
                    items_updated=partial_updated,
                    source_reported_count=exc.source_reported_count,
                    next_cursor=partial_cursor,
                )
                paused_shard_run.status = RUN_STATUS_PAUSED
                paused_shard_run.finished_at = None
                paused_shard_run.coverage_complete = False
                paused_shard_run.error = f"{type(exc).__name__}: {exc}"

                handoff_count += 1
                if handoff_count > max(1, max_challenge_handoffs_per_run):
                    paused_shard_run.status = RunStatus.FAILED
                    paused_shard_run.finished_at = datetime.now(UTC)
                    paused_shard_run.error = (
                        f"ChallengeHandoffLimit: exceeded {max_challenge_handoffs_per_run} handoffs"
                    )
                    paused_shard.consecutive_failures += 1
                    _mark_unattempted_after_source_halt(
                        session,
                        run_id=run_id,
                        source_name=source.name,
                        failed_spec_key=spec.key,
                        remaining_shards=ordered_shards[index + 1 :],
                        reason=paused_shard_run.error,
                    )
                    session.commit()
                    halt_reason = paused_shard_run.error
                    break

                state_dir = (
                    challenge_state_root
                    / source.name
                    / f"run-{run_id}"
                    / f"shard-{shard_id}"
                    / f"handoff-{handoff_count}"
                )
                handoff_state = await adapter.prepare_challenge_handoff(
                    state_dir=state_dir,
                    challenge=exc,
                )
                request = ChallengeRequest(
                    source=source.name,
                    run_id=run_id,
                    shard_id=shard_id,
                    shard_key=spec.key,
                    shard_params=dict(spec.params),
                    mode=str(mode),
                    reason=str(exc),
                    challenge=dict(exc.challenge),
                    resume_cursor=dict(partial_cursor),
                    handoff_state=dict(handoff_state),
                )
                metadata = dict(paused_run.run_metadata or {})
                metadata["active_challenge"] = request.to_payload()
                paused_run.run_metadata = metadata
                summary = checkpoint_paused_run(session, paused_run)
                _queue_house_refresh(session, paused_source, paused_run, summary)
                session.commit()

                result = await handler.handle(request)
                paused_run = session.get(CrawlRun, run_id)
                paused_shard_run = session.get(CrawlShardRun, shard_run_id)
                paused_shard = session.get(SourceShard, shard_id)
                if paused_run is None or paused_shard_run is None or paused_shard is None:
                    raise RuntimeError(f"Challenge handler lost run {run_id} state")
                _record_challenge_result(
                    paused_run,
                    request,
                    action=result.action,
                    message=result.message,
                )

                if result.action == "defer":
                    metadata = dict(paused_run.run_metadata or {})
                    metadata["active_challenge"] = request.to_payload()
                    paused_run.run_metadata = metadata
                    summary = checkpoint_paused_run(session, paused_run)
                    return paused_run, summary
                if result.action == "abort":
                    paused_shard_run.status = RunStatus.FAILED
                    paused_shard_run.finished_at = datetime.now(UTC)
                    paused_shard_run.coverage_complete = False
                    paused_shard_run.error = result.message or "user challenge handler aborted"
                    paused_shard.consecutive_failures += 1
                    _mark_unattempted_after_source_halt(
                        session,
                        run_id=run_id,
                        source_name=source.name,
                        failed_spec_key=spec.key,
                        remaining_shards=ordered_shards[index + 1 :],
                        reason=paused_shard_run.error,
                    )
                    session.commit()
                    halt_reason = paused_shard_run.error
                    break

                if result.retry_after_seconds:
                    await asyncio.sleep(result.retry_after_seconds)
                await adapter.restore_challenge_handoff(request.handoff_state)
                paused_shard_run.status = RunStatus.RUNNING
                paused_shard_run.finished_at = None
                paused_shard_run.error = None
                paused_run.status = RunStatus.RUNNING
                paused_run.coverage_status = CoverageStatus.UNKNOWN
                session.commit()
                resume_cursor = dict(partial_cursor)
                continue
            except Exception as exc:
                halt_reason = _source_halt_reason(exc)
                session.rollback()
                partial_seen = 0
                partial_new = 0
                partial_updated = 0
                partial_cursor: dict[str, Any] = {}
                if isinstance(exc, SourceFetchError):
                    partial_seen, partial_new, partial_updated, partial_cursor = await _ingest_partial_fetch(
                        session,
                        source_id=source_id,
                        run_id=run_id,
                        exc=exc,
                    )

                failed_shard_run = session.get(CrawlShardRun, shard_run_id)
                failed_shard = session.get(SourceShard, shard_id)
                if failed_shard_run is None or failed_shard is None:
                    raise RuntimeError(
                        f"Could not reload failed shard state for {source.name}/{spec.key}"
                    ) from exc

                failed_shard_run.status = RunStatus.FAILED
                failed_shard_run.finished_at = datetime.now(UTC)
                failed_shard_run.coverage_complete = False
                failed_shard_run.error = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, SourceFetchError):
                    _apply_attempt_metrics(
                        failed_shard_run,
                        pages_fetched=exc.pages_fetched,
                        items_seen=partial_seen,
                        items_new=partial_new,
                        items_updated=partial_updated,
                        source_reported_count=exc.source_reported_count,
                        next_cursor=partial_cursor,
                    )
                failed_shard.consecutive_failures += 1
                session.commit()
                break

        if halt_reason is not None:
            _mark_unattempted_after_source_halt(
                session,
                run_id=run_id,
                source_name=source.name,
                failed_spec_key=spec.key,
                remaining_shards=ordered_shards[index + 1 :],
                reason=halt_reason,
            )
            session.commit()
            break

    run = session.get(CrawlRun, run_id)
    source = session.get(Source, source_id)
    if run is None or source is None:
        raise RuntimeError(f"Could not reload completed run {run_id}")
    summary = finalize_run(session, run)
    if reconciliation and summary.coverage_status == CoverageStatus.OK:
        reconcile_immmo_continuity(session, run)
        reconcile_missing_listings(session, run)
    _queue_house_refresh(session, source, run, summary)
    session.commit()
    return run, summary
