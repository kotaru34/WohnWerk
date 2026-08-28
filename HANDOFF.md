# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-28 (Europe/Berlin)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This file is the authoritative recovery point for continuing WohnWerk in a fresh context.

## Product direction / invariants

WohnWerk is a private/self-hosted Austria-first house + job acquisition, personalization and matching system.

- End-user UI is German only.
- Never request or print DB/API credentials.
- `JobListing.status` is source lifecycle only.
- Professional relevance is independent in `raw_payload["wohnwerk_discovery_gate"]`.
- Candidate fit/preferences are independent and recomputable.
- Failed/partial frontier runs never mass-deactivate.
- Do not invent Austrian PLZ/location points; preserve source provenance.
- Geography is separate from intrinsic fit; use PostGIS rather than permanent NxM pairs.
- No CAPTCHA bypass, credential theft, fingerprint spoofing or deliberate anti-bot evasion.

## Stable acquisition

Properties:
- IMMMO #11: coverage OK, 13,948 seen, 1,167 pages, 9/9 shards.
- s REAL #16: coverage OK, 314 seen, detail-enriched.
- ImmoAds retired/disabled.

Supplementary ATS jobs:
- SmartRecruiters #33: 42 relevant-active canonical jobs; 41/42 relevant locations resolved.
- Personio #37: 17 relevant-active jobs; only `österreichweit` intentionally unresolved.
- Lever #22: 6 relevant jobs, all relevant locations resolved.

Low-impact broad boards:
- karriere.at #40: 30 relevant jobs, 35 requests, 27 structured salaries.
- jobs.at #41: 13 relevant jobs, 18 requests, 12 structured salaries + 1 salary text.
- StepStone #45: 37 relevant jobs, exactly 5 requests, zero details, 27 geo-resolved.
- willhaben #46: 18 relevant jobs, exactly 5 requests, zero details, source_reported=448.

Acquisition micro-polishing is paused intentionally.

## Discovery gate / candidate direction

Current discovery gate: `profile-seed-2026-08-28-v14`. Generic discovery correctness is closed unless a genuinely generic bug appears.

Candidate is fundamentally mechanical/Maschinenbau, not electrical. Future fit should strongly prefer mechanical CAD/construction, components/assemblies, automotive/special-vehicle/rail work, product development, technical project work, supplier coordination and mechanically relevant validation/testing. Pure electrical engineering is `cannot + not want`; this affects candidate fit, not broad acquisition.

## Canonical job dedupe — closed

Seven explicit fail-closed groups were merged. Corpus moved from `163 / 0` relevant canonical / multi-listing canonical jobs to `156 / 7`.

Final production audit:
- `duplicate_candidates_high=0`
- `duplicate_candidates_blocked=1`
- `duplicate_candidates_medium=6`

Blocked teampool 163/168 remains split because source locations conflict (`Wien` vs `Wels`). Medium TSMG/Austro Holding/Trenkwalder/Anton Paar candidates remain untouched.

Merge is explicit-ID, dry-run by default and fail-closed on company/salary/evidence/same-source location conflicts. Source listings/raw payloads survive canonical merge. Audit and destructive safety use the same merge plan.

Canonical dedupe is intentionally closed for the current corpus.

## Normalized job concepts — production established

Dimensions:
- `role`
- `domain`
- `task`
- `method`
- `tool`

Files:
- `app/jobs/concepts.py`
- `app/jobs/concept_catalog.py`
- `migrations/versions/0007_job_concepts.py`
- `scripts/normalize_job_concepts.py`
- `scripts/job_concept_persisted_audit.py`
- `tests/test_job_concepts.py`

Vocabulary is canonical `JobConcept` + many `JobConceptAlias` rows. `JobConceptEvidence` stores concept, alias, field, semantic scope, confidence and extractor version. Evidence is recomputable and candidate-independent.

### Extractor v2 / evidence semantics

Current deterministic extractor: `concept-seed-2026-08-28-v2`.

Phrase occurrence is explicitly classified:
- title -> `scope=primary`, confidence `1.00`
- description role -> `scope=context`, confidence `0.45`
- description domain -> `scope=context`, confidence `0.55`
- description task -> `scope=context`, confidence `0.80`
- description method/tool -> `scope=context`, confidence `0.85`

This keeps description requirements useful without allowing text such as `Studium Maschinenbau, Mechatronik oder Elektrotechnik` to redefine the vacancy as three primary domains.

Guardrails:
- generic `Konstrukteur` is a generic designer role, not automatic mechanical-engineering;
- EPLAN alone does not imply electrical-engineering;
- FEM cannot substring-match `female`;
- deterministic recompute replaces prior `concept-seed-*` evidence only;
- DB-enabled concepts/aliases drive applied extraction, so future admin UI edits do not require Python changes.

### Production migration + persist completed

Migration `0007_job_concepts` was applied successfully from `0006_job_source_tenants` and is currently installed in production.

Production `normalize_job_concepts.py --apply` result:
- `relevant_active_jobs=156`
- `jobs_with_concepts=156`
- `jobs_without_concepts=0`
- `distinct_concepts_matched=49`
- `evidence_rows=747`
- `evidence_primary=219`
- `evidence_context=528`
- jobs/evidence by kind:
  - role `115 / 229`
  - domain `125 / 268`
  - task `86 / 176`
  - method `11 / 11`
  - tool `38 / 63`

Persisted DB audit confirmed exactly:
- `persisted_evidence_rows=747`
- `persisted_jobs=156`
- `persisted_primary=219`
- `persisted_context=528`
- `invalid_scope_values=-`
- only deterministic version present: `concept-seed-2026-08-28-v2 rows=747`

Targeted persisted checks also matched dry-run:
- `domain:electrical-engineering`: 40 jobs, primary=4, context=38
- `role:mechanical-technician`: 23 jobs, primary=21, context=8
- `role:designer-engineer`: 48 jobs, primary=44, context=32

Normalization is now considered production-established. Do not continue synonym polishing without a demonstrated fit/precision problem.

## Candidate concept preferences / fit — current primary work

New files:
- `app/jobs/candidate_fit.py` — ORM preference models + pure versioned scoring engine
- `app/jobs/candidate_profile_seed.py` — conservative initial profile seed
- `migrations/versions/0008_candidate_preferences.py`
- `scripts/candidate_fit_audit.py` — read-only production ranking audit
- `tests/test_candidate_fit.py`
- `migrations/env.py` imports candidate preference models for complete Alembic metadata

### Four-state model

`CandidateConceptPreference` stores exactly one of:
- `can_want`
- `can_not_want`
- `cannot_want`
- `cannot_not_want`

DB migration `0008` includes a check constraint for these four states. Absence of a preference row means **unrated**; uncertain concepts are not forced into a guessed state.

`CandidateProfile` makes the architecture profile-aware rather than hardcoding one candidate.

### Fit policy v1

Current dry-run policy: `candidate-fit-2026-08-28-v1`.

State values:
- can + want = `+1.00`
- can + not want = `-0.20`
- cannot + want = `+0.20`
- cannot + not want = `-1.00`

Kind weights:
- role `1.15`
- domain `1.25`
- task `1.00`
- method/tool `0.75`

Scope amplitude:
- primary `1.00`
- context `0.35`

Important math guard: normalization uses the unscoped evidence strength while contribution amplitude uses scope. Therefore context attenuation cannot cancel out in numerator/denominator. A pure primary `cannot_not_want` domain can reach score 0, while the same concept present only as description context is only moderately negative (about 32–33), not an extreme identity signal.

Repeated title/description evidence for the same concept collapses to the strongest signal. Unrated concepts do not bias score but reduce `preference_coverage`.

`Job.job_fit_score` already exists historically but is **not** the source of truth and is not mutated by the current audit. It may later be used only as a materialized/cache value after policy validation.

### Initial profile seed

Seed version: `candidate-profile-2026-08-28-v1`.

It intentionally rates only established concepts and leaves uncertain tool/role/domain concepts unrated. It includes positive mechanical/product/project/task evidence and explicit negative pure electrical domain. Generic cross-domain `designer-engineer` is intentionally not rated positive by itself; domain/task evidence must establish specialization.

### Safety / tests

Regression tests cover:
- primary mechanical evidence dominating conflicting electrical context;
- pure primary electrical `cannot_not_want` scoring at the bottom;
- context-only negative evidence being attenuated rather than normalized back to an extreme;
- unrated concepts lowering coverage without biasing signed score;
- repeated evidence collapsing to the strongest signal;
- middle states remaining directionally distinct;
- no rated evidence returning no score.

CI #423 passed Ruff, Compile and the full suite after the context-normalization fix.

## Immediate work order

1. Pull latest `bootstrap/austria-mvp`.
2. **Do not apply migration 0008 yet.**
3. Run only the read-only live fit audit:

   `python scripts/candidate_fit_audit.py --limit 25`

4. Inspect:
   - `jobs_scored/jobs_unscored`
   - score mean/median
   - preference coverage mean/median
   - top 25 and bottom 25 titles/companies
   - printed concept drivers for obvious false positives/negatives
5. If useful, rerun selected suspicious jobs with repeatable `--job-id ID` for full contribution detail.
6. Tune fit policy/profile seed only from actual ranking evidence.
7. Once ranking semantics are healthy, apply migration 0008 and persist the profile/preferences.
8. Then build German admin UI for concept/profile rating and recompute materialized `Job.job_fit_score` from persisted profile state.
9. After intrinsic fit is stable, combine with PostGIS house/job distance, salary and final recommendation ranking.
