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

Current deterministic extractor: `concept-seed-2026-08-28-v2`.

Evidence semantics:
- title -> `primary / 1.00`
- description role -> `context / 0.45`
- description domain -> `context / 0.55`
- description task -> `context / 0.80`
- description method/tool -> `context / 0.85`

Guardrails:
- generic `Konstrukteur` is generic designer role, not automatic mechanical domain;
- EPLAN alone does not imply electrical domain;
- FEM cannot substring-match `female`;
- deterministic recompute replaces prior `concept-seed-*` evidence only;
- DB-enabled aliases drive applied extraction.

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

Normalization is production-established. Do not broadly polish synonyms again without a demonstrated ranking/precision problem.

## Candidate concept preferences / fit — current primary work

Files:
- `app/jobs/candidate_fit.py`
- `app/jobs/candidate_profile_seed.py`
- `migrations/versions/0008_candidate_preferences.py`
- `scripts/candidate_fit_audit.py`
- `tests/test_candidate_fit.py`

Four states:
- `can_want`
- `can_not_want`
- `cannot_want`
- `cannot_not_want`

Absence of a preference row means **unrated**. Candidate profiles are first-class. `Job.job_fit_score` is not source of truth and remains untouched by audits.

Initial seed: `candidate-profile-2026-08-28-v1`, with 23 rated concepts. Generic `designer-engineer` and uncertain tools/roles/domains remain unrated. `domain:electrical-engineering` is explicit `cannot_not_want`.

### First production fit audit — policy v1

Read-only audit on all 156 jobs using `candidate-fit-2026-08-28-v1`:
- `jobs_scored=136`
- `jobs_unscored=20`
- `score_mean=75.71`
- `score_median=73.00`
- `preference_coverage_mean=0.592`
- `preference_coverage_median=0.521`

Two distinct issues were demonstrated:

1. **Positive saturation bug:** one positive generic role/domain could normalize to 100. This made development-engineer-only and mechanical-domain-only jobs appear perfect.
2. **Narrow taxonomy gap:** obvious electrical/electronics identity titles such as `Elektronik-Entwicklungsingenieur`, `Head of Electronics`, `EMC Engineer`, `Hardware Engineer` do not necessarily have primary electrical-domain evidence.

Examples from v1:
- `Konstrukteur*in Elektrotechnik` -> 0, correct hard-negative primary electrical identity.
- context-only electrical mentions -> about 32–56 depending on positive context, showing scope attenuation works.
- `Entwicklungsingenieur Elektrotechnik` -> about 48 because primary negative electrical and primary positive generic development nearly cancel.
- `Elektronik-Entwicklungsingenieur ... Produktentwicklung` -> false 100 because electrical/electronics identity is missing and two generic positives saturated.

### Fit policy v2 — current code

Current policy: `candidate-fit-2026-08-28-v2`.

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

New rule: **positive evidence budget = 3.0**. Positive fit normalizes against at least 3.0 evidence weight so one attractive generic concept cannot saturate.

Approximate behavior:
- one primary role -> ~69
- one primary domain -> ~71
- primary role + domain -> ~90
- role + domain + task can reach 100

Negative evidence intentionally has no optimism floor: a primary `cannot_not_want` domain can still veto to 0. Context-only hard-negative stays attenuated around 32.

`candidate_fit_audit.py --job-id` now prints every persisted concept for the job, including `unrated`, not only scored drivers. This allows the next pass to distinguish weighting problems from missing taxonomy evidence.

Regression tests cover positive saturation, corroborating multi-concept fit, primary hard-negative veto, context attenuation, unrated coverage and duplicate-evidence collapse.

CI #428 passed Ruff, Compile and the full suite for policy v2 and expanded audit evidence.

## Immediate work order

1. Pull latest `bootstrap/austria-mvp`.
2. **Do not apply migration 0008 yet.**
3. Run read-only policy-v2 ranking plus detailed suspicious-job evidence:

   `python scripts/candidate_fit_audit.py --limit 25 --job-id 259 --job-id 15 --job-id 21 --job-id 89 --job-id 128 --job-id 254 --job-id 28`

4. Inspect score distribution/top/bottom plus full evidence for those IDs.
5. Verify whether #259/#15/#21/#89/#128 demonstrate a missing explicit electrical/electronics identity concept rather than another scoring problem.
6. If confirmed, make one narrow extractor v3 refinement for explicit electrical/electronics title wording. Do not broadly reopen vocabulary work.
7. Dry-run v3 normalization, then persist deterministic evidence if clean.
8. Re-run fit audit.
9. Once fit semantics are healthy, apply migration 0008 and persist candidate preferences.
10. Build German admin UI for four-state concept/profile rating and materialized fit recompute.
11. Then combine intrinsic fit with PostGIS house/job distance, salary and final recommendation ranking.
