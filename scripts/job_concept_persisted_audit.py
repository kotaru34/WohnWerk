from __future__ import annotations

import argparse
from collections import Counter, defaultdict

from sqlalchemy import select

from app.database import SessionLocal
from app.jobs.concept_catalog import EXTRACTOR_VERSION
from app.jobs.concepts import ConceptKind, JobConcept, JobConceptEvidence
from app.models import Job


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit persisted normalized job-concept evidence without modifying the database."
    )
    parser.add_argument(
        "--audit-concept",
        action="append",
        default=[],
        metavar="KIND:SLUG",
        help="Print persisted evidence for a concept; may be repeated.",
    )
    parser.add_argument(
        "--audit-limit",
        type=int,
        default=20,
        help="Maximum jobs printed per audited concept (default: 20).",
    )
    return parser.parse_args()


def _parse_concepts(values: list[str]) -> list[tuple[str, str]]:
    valid_kinds = {kind.value for kind in ConceptKind}
    parsed: list[tuple[str, str]] = []
    for value in values:
        kind, separator, slug = value.partition(":")
        if not separator or kind not in valid_kinds or not slug:
            raise ValueError(
                f"invalid --audit-concept {value!r}; expected KIND:SLUG with kind in "
                f"{','.join(sorted(valid_kinds))}"
            )
        parsed.append((kind, slug))
    return parsed


def main() -> None:
    args = parse_args()
    audit_concepts = _parse_concepts(args.audit_concept)

    with SessionLocal() as session:
        deterministic_versions = Counter(
            session.scalars(
                select(JobConceptEvidence.extractor_version).where(
                    JobConceptEvidence.extractor_version.like("concept-seed-%")
                )
            )
        )
        rows = session.execute(
            select(JobConceptEvidence, JobConcept, Job)
            .join(JobConcept, JobConcept.id == JobConceptEvidence.concept_id)
            .join(Job, Job.id == JobConceptEvidence.job_id)
            .where(JobConceptEvidence.extractor_version == EXTRACTOR_VERSION)
            .order_by(JobConcept.kind, JobConcept.slug, Job.id, JobConceptEvidence.field)
        ).all()

    jobs = {job.id for _evidence, _concept, job in rows}
    scopes = Counter(evidence.scope for evidence, _concept, _job in rows)
    invalid_scopes = sorted(scope for scope in scopes if scope not in {"primary", "context"})
    by_concept: dict[tuple[str, str], list[tuple[JobConceptEvidence, Job]]] = defaultdict(list)
    for evidence, concept, job in rows:
        by_concept[(concept.kind, concept.slug)].append((evidence, job))

    print(f"extractor_version={EXTRACTOR_VERSION}")
    print(f"persisted_evidence_rows={len(rows)}")
    print(f"persisted_jobs={len(jobs)}")
    print(f"persisted_primary={scopes['primary']}")
    print(f"persisted_context={scopes['context']}")
    print(f"invalid_scope_values={','.join(invalid_scopes) if invalid_scopes else '-'}")
    print("deterministic_versions:")
    for version, count in sorted(deterministic_versions.items()):
        print(f"  {version} rows={count}")

    if audit_concepts:
        print("audited_concepts:")
        for key in audit_concepts:
            concept_rows = by_concept.get(key, [])
            concept_jobs = {job.id for _evidence, job in concept_rows}
            primary = sum(evidence.scope == "primary" for evidence, _job in concept_rows)
            context = sum(evidence.scope == "context" for evidence, _job in concept_rows)
            print(
                f"  {key[0]}:{key[1]} jobs={len(concept_jobs)} "
                f"primary={primary} context={context}"
            )
            printed_jobs: set[int] = set()
            for evidence, job in concept_rows:
                if job.id in printed_jobs:
                    continue
                if len(printed_jobs) >= max(0, args.audit_limit):
                    break
                job_evidence = [
                    row_evidence
                    for row_evidence, row_job in concept_rows
                    if row_job.id == job.id
                ]
                evidence_label = ", ".join(
                    f"{item.field}/{item.scope}/{float(item.confidence):.2f}:{item.matched_text!r}"
                    for item in job_evidence
                )
                print(f"    job={job.id} title={job.title} evidence={evidence_label}")
                printed_jobs.add(job.id)

    print("mode=read-only no database changes")


if __name__ == "__main__":
    main()
