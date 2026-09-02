from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.database import SessionLocal
from app.jobs.concept_catalog import (
    CONCEPT_SEEDS,
    EXTRACTOR_VERSION,
    ConceptMatch,
    ConceptSeed,
    JobTextSnapshot,
    extract_concepts,
    normalize_concept_text,
)
from app.jobs.concepts import (
    ConceptKind,
    JobConcept,
    JobConceptAlias,
    JobConceptEvidence,
    concept_evidence_semantics,
)
from app.models import Job, JobListing, ListingStatus


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize relevant canonical jobs into role/domain/task/method/tool concepts. "
            "Dry-run by default; --apply seeds the vocabulary and replaces evidence for "
            "the current extractor version."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist vocabulary/evidence. Without this flag the command is read-only.",
    )
    parser.add_argument(
        "--unmatched-limit",
        type=int,
        default=20,
        help="Maximum unmatched job titles to print in the summary (default: 20).",
    )
    parser.add_argument(
        "--audit-concept",
        action="append",
        default=[],
        metavar="KIND:SLUG",
        help="Print matching jobs/evidence for a concept; may be repeated.",
    )
    parser.add_argument(
        "--audit-limit",
        type=int,
        default=20,
        help="Maximum jobs printed per audited concept (default: 20).",
    )
    return parser.parse_args()


def _gate_accepted(listing: JobListing) -> bool:
    payload = listing.raw_payload or {}
    gate = payload.get("wohnwerk_discovery_gate")
    return isinstance(gate, dict) and gate.get("accepted") is True


def _relevant_active_jobs(session: Session) -> list[Job]:
    jobs = list(
        session.scalars(
            select(Job)
            .where(Job.status == ListingStatus.ACTIVE)
            .options(selectinload(Job.listings))
            .order_by(Job.id)
        )
    )
    return [
        job
        for job in jobs
        if any(
            listing.status == ListingStatus.ACTIVE and _gate_accepted(listing)
            for listing in job.listings
        )
    ]


def _seed_vocabulary(session: Session) -> None:
    existing = {
        (concept.kind, concept.slug): concept
        for concept in session.scalars(select(JobConcept))
    }
    for seed in CONCEPT_SEEDS:
        key = (seed.kind.value, seed.slug)
        concept = existing.get(key)
        if concept is None:
            concept = JobConcept(
                kind=seed.kind.value,
                slug=seed.slug,
                label_de=seed.label_de,
                enabled=True,
            )
            session.add(concept)
            session.flush()
            existing[key] = concept
        elif concept.label_de != seed.label_de:
            concept.label_de = seed.label_de

        aliases = {
            alias.normalized_alias: alias
            for alias in session.scalars(
                select(JobConceptAlias).where(JobConceptAlias.concept_id == concept.id)
            )
        }
        for surface in seed.aliases:
            normalized = normalize_concept_text(surface)
            if normalized in aliases:
                continue
            alias = JobConceptAlias(
                concept_id=concept.id,
                alias=surface,
                normalized_alias=normalized,
                language=None,
                source="seed",
                enabled=True,
            )
            session.add(alias)
            aliases[normalized] = alias
    session.flush()


def _database_catalog(session: Session) -> tuple[ConceptSeed, ...]:
    concepts = list(
        session.scalars(
            select(JobConcept)
            .where(JobConcept.enabled.is_(True))
            .options(selectinload(JobConcept.aliases))
            .order_by(JobConcept.kind, JobConcept.slug)
        )
    )
    return tuple(
        ConceptSeed(
            kind=ConceptKind(concept.kind),
            slug=concept.slug,
            label_de=concept.label_de,
            aliases=tuple(alias.alias for alias in concept.aliases if alias.enabled),
        )
        for concept in concepts
        if any(alias.enabled for alias in concept.aliases)
    )


def _extract(
    jobs: list[Job],
    catalog: tuple[ConceptSeed, ...],
) -> dict[int, list[ConceptMatch]]:
    return {
        job.id: extract_concepts(
            JobTextSnapshot(job_id=job.id, title=job.title, description=job.description),
            catalog=catalog,
        )
        for job in jobs
    }


def _concept_key(match: ConceptMatch) -> tuple[str, str]:
    return match.kind.value, match.slug


def _parse_audit_concepts(values: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    valid_kinds = {kind.value for kind in ConceptKind}
    for value in values:
        kind, separator, slug = value.partition(":")
        if not separator or kind not in valid_kinds or not slug:
            raise ValueError(
                f"invalid --audit-concept {value!r}; expected KIND:SLUG with kind in "
                f"{','.join(sorted(valid_kinds))}"
            )
        parsed.append((kind, slug))
    return parsed


def _print_summary(
    jobs: list[Job],
    matches_by_job: dict[int, list[ConceptMatch]],
    unmatched_limit: int,
    audit_concepts: list[tuple[str, str]],
    audit_limit: int,
) -> None:
    matched_jobs = [job for job in jobs if matches_by_job[job.id]]
    evidence_count = sum(len(matches) for matches in matches_by_job.values())
    concept_keys = {
        _concept_key(match)
        for matches in matches_by_job.values()
        for match in matches
    }
    by_kind = Counter(
        match.kind.value
        for matches in matches_by_job.values()
        for match in matches
    )
    jobs_by_kind: dict[str, set[int]] = defaultdict(set)
    jobs_by_concept: dict[tuple[str, str], set[int]] = defaultdict(set)
    scopes_by_concept: Counter[tuple[str, str, str]] = Counter()
    scope_totals: Counter[str] = Counter()
    for job_id, matches in matches_by_job.items():
        for match in matches:
            key = _concept_key(match)
            scope, _confidence = concept_evidence_semantics(match.kind, match.field)
            jobs_by_kind[match.kind.value].add(job_id)
            jobs_by_concept[key].add(job_id)
            scopes_by_concept[(*key, scope.value)] += 1
            scope_totals[scope.value] += 1

    print(f"extractor_version={EXTRACTOR_VERSION}")
    print(f"relevant_active_jobs={len(jobs)}")
    print(f"jobs_with_concepts={len(matched_jobs)}")
    print(f"jobs_without_concepts={len(jobs) - len(matched_jobs)}")
    print(f"distinct_concepts_matched={len(concept_keys)}")
    print(f"evidence_rows={evidence_count}")
    print(f"evidence_primary={scope_totals['primary']}")
    print(f"evidence_context={scope_totals['context']}")
    for kind in ("role", "domain", "task", "method", "tool"):
        print(f"jobs_{kind}={len(jobs_by_kind[kind])}")
        print(f"evidence_{kind}={by_kind[kind]}")

    ranked_concepts = sorted(
        concept_keys,
        key=lambda key: (-len(jobs_by_concept[key]), key[0], key[1]),
    )
    print("top_concepts:")
    for kind, slug in ranked_concepts[:40]:
        key = (kind, slug)
        print(
            f"  {kind}:{slug} jobs={len(jobs_by_concept[key])} "
            f"primary={scopes_by_concept[(*key, 'primary')]} "
            f"context={scopes_by_concept[(*key, 'context')]}"
        )

    unmatched = [job for job in jobs if not matches_by_job[job.id]]
    if unmatched:
        print("unmatched_jobs:")
        for job in unmatched[: max(0, unmatched_limit)]:
            print(f"  job={job.id} title={job.title}")

    if audit_concepts:
        jobs_by_id = {job.id: job for job in jobs}
        print("audited_concepts:")
        for key in audit_concepts:
            matching_job_ids = sorted(jobs_by_concept.get(key, set()))
            print(f"  {key[0]}:{key[1]} jobs={len(matching_job_ids)}")
            for job_id in matching_job_ids[: max(0, audit_limit)]:
                evidence = [
                    match
                    for match in matches_by_job[job_id]
                    if _concept_key(match) == key
                ]
                evidence_parts = []
                for match in evidence:
                    scope, confidence = concept_evidence_semantics(match.kind, match.field)
                    evidence_parts.append(
                        f"{match.field}/{scope.value}/{confidence:.2f}:{match.alias!r}"
                    )
                print(
                    f"    job={job_id} title={jobs_by_id[job_id].title} "
                    f"evidence={', '.join(evidence_parts)}"
                )


def _persist(
    session: Session,
    jobs: list[Job],
    matches_by_job: dict[int, list[ConceptMatch]],
) -> None:
    _seed_vocabulary(session)
    catalog = _database_catalog(session)
    matches_by_job.clear()
    matches_by_job.update(_extract(jobs, catalog))

    concepts = {
        (concept.kind, concept.slug): concept
        for concept in session.scalars(select(JobConcept))
    }
    aliases: dict[tuple[int, str], JobConceptAlias] = {}
    for alias in session.scalars(select(JobConceptAlias)):
        aliases[(alias.concept_id, alias.normalized_alias)] = alias

    session.execute(
        delete(JobConceptEvidence).where(
            JobConceptEvidence.extractor_version.like("concept-seed-%")
        )
    )

    for matches in matches_by_job.values():
        for match in matches:
            concept = concepts[(match.kind.value, match.slug)]
            alias = aliases[(concept.id, match.normalized_alias)]
            scope, confidence = concept_evidence_semantics(match.kind, match.field)
            session.add(
                JobConceptEvidence(
                    job_id=match.job_id,
                    concept_id=concept.id,
                    alias_id=alias.id,
                    field=match.field,
                    scope=scope.value,
                    matched_text=match.alias,
                    confidence=Decimal(str(confidence)),
                    extractor_version=EXTRACTOR_VERSION,
                )
            )
    session.commit()


def main() -> None:
    args = parse_args()
    audit_concepts = _parse_audit_concepts(args.audit_concept)
    with SessionLocal() as session:
        jobs = _relevant_active_jobs(session)
        matches_by_job = _extract(jobs, CONCEPT_SEEDS)
        _print_summary(
            jobs,
            matches_by_job,
            args.unmatched_limit,
            audit_concepts,
            args.audit_limit,
        )

        if not args.apply:
            print("mode=dry-run no database changes")
            return

        _persist(session, jobs, matches_by_job)
        print("mode=apply")
        print(
            "persisted_evidence_rows="
            f"{sum(len(matches) for matches in matches_by_job.values())}"
        )


if __name__ == "__main__":
    main()
