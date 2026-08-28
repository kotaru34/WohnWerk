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

Migration `0007_job_concepts` is applied in production.

Persisted state:
- `156/156` relevant jobs matched
- `49` distinct concepts
- `747` evidence rows
- `219 primary / 528 context`
- `invalid_scope_values=-`
- only `concept-seed-2026-08-28-v2` deterministic evidence present

Targeted persisted checks:
- `domain:electrical-engineering`: 40 jobs, primary=4, context=38
- `role:mechanical-technician`: 23 jobs, primary=21, context=8
- `role:designer-engineer`: 48 jobs, primary=44, context=32

Normalization is production-established. Do not continue broad synonym polishing without a demonstrated fit/precision problem.

## Candidate concept preferences / fit — current primary work

Files:
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

Migration `0008` has a four-state DB check constraint. Absence of a preference row means **unrated**; uncertain concepts are not guessed.

`CandidateProfile` makes the architecture profile-aware rather than hardcoding one candidate.

`Job.job_fit_score` exists historically but is not the source of truth and is not mutated by current audits. It may later be materialized/cache only.

### Initial profile seed

Seed version: `candidate-profile-2026-08-28-v1`.

It rates only established profile facts. Positive concepts include mechanical engineering/design, development/project roles, automotive/special vehicle/rail/special machinery, product development, project/requirements/supplier/testing/assembly/calculation/documentation tasks, FEM and FMEA. `domain:electrical-engineering` is explicit `cannot_not_want`. Generic cross-domain `designer-engineer` remains unrated.

### First production fit audit — policy v1

Read-only audit on all 156 jobs using `candidate-fit-2026-08-28-v1` produced:
- rated concepts: 23
- jobs scored: 136
- jobs unscored: 20
- score mean: 75.71
- score median: 73.00
- preference coverage mean: 0.592
- preference coverage median: 0.521

The audit exposed two distinct correctness issues:

1. **Positive saturation bug.** A single positive generic role/domain could normalize to score 100. This caused many weakly evidenced jobs to rank as perfect fits, including development-engineer-only and Maschinenbautechniker jobs whose only rated positive signal was mechanical domain.

2. **Targeted taxonomy gap.** Obvious electrical/electronics identity titles such as `Elektronik-Entwicklungsingenieur`, `Head of Electronics`, `EMC Engineer`, `Hardware Engineer` do not yet necessarily have primary electrical-domain evidence. This is a narrow demonstrated normalization problem, not a reason to reopen broad synonym polishing.

Useful v1 observations:
- true primary electrical title `Konstrukteur*in Elektrotechnik` scored 0 as intended;
- context-only electrical mentions landed around 32–56 depending on positive context, confirming primary/context attenuation works;
- `Entwicklungsingenieur Elektrotechnik` landed around 48 because primary negative electrical domain and primary positive generic development role nearly cancel;
- `Elektronik-Entwicklungsingenieur ... Produktentwicklung` falsely reached 100 because electrical/electronics identity was missing from normalization and two generic positives saturated the score.

### Fit policy v2 — current code

Current dry-run policy: `candidate-fit-2026-08-28-v2`.

State values remain:
- can + want = `+1.00`
- can + not want = `-0.20`
- cannot + want = `+0.20`
- cannot + not want = `-1.00`

Kind weights remain:
- role `1.15`
- domain `1.25`
- task `1.00`
- method/tool `0.75`

Scope amplitude remains:
- primary `1.00`
- context `0.35`

New rule: **positive evidence budget = 3.0**. Positive fit is normalized against at least 3.0 evidence weight, so one generic positive cannot claim an exceptional fit. Approximate behavior:
- one primary role -> score ~69
- one primary domain -> ~71
- primary role + domain -> ~90
- role + domain + task can reach 100

Negative evidence intentionally has no optimism floor: a primary `cannot_not_want` domain can still veto to 0. Context-only hard-negative remains attenuated around 32 rather than becoming an extreme identity signal.

Audit `--job-id` output now prints all persisted evidence for that job, including unrated concepts, so the next pass can distinguish scorer problems from missing normalization evidence.

Regression tests cover positive saturation, corroborating multi-concept fit, primary hard-negative veto, context attenuation, unrated coverage and duplicate-evidence collapse.

CI #428 passed Ruff, Compile and the full suite for policy v2 and expanded audit evidence.

## Immediate work order

1. Pull latest `bootstrap/austria-mvp`.
2. **Do not apply migration 0008 yet.**
3. Run policy-v2 read-only ranking plus detailed suspicious-job evidence:

   `python scripts/candidate_fit_audit.py --limit 25 --job-id 259 --job-id 15 --job-id 21 --job-id 89 --job-id 128 --job-id 254 --job-id 28`

4. Inspect:
   - score mean/median and whether false 100s collapse;
   - top/bottom ordering;
   - full rated/unrated evidence for electronics/electrical examples;
   - whether #259/#15/#21 clearly demonstrate a missing title-domain concept rather than a weighting issue.
5. If confirmed, make one narrow extractor v3 refinement for explicit electrical/electronics identity wording; do not broadly expand synonyms.
6. Recompute/persist deterministic concept evidence only after a read-only v3 audit.
7. Re-run fit audit.
8. Once ranking semantics are healthy, apply migration 0008 and persist profile preferences.
9. Then build German admin UI for four-state concept/profile rating and materialized fit recompute.
10. After intrinsic fit is stable, combine with PostGIS house/job distance, salary and final recommendation ranking.
