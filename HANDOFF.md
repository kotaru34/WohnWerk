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

Candidate is fundamentally mechanical/Maschinenbau, not electrical/electronics. Fit should strongly prefer mechanical CAD/construction, components/assemblies, automotive/special-vehicle/rail work, product development, technical project work, supplier coordination and mechanically relevant validation/testing. Pure electrical/electronics work is `cannot + not want`; this affects candidate fit, not broad acquisition.

## Canonical job dedupe — closed

Seven explicit fail-closed groups were merged. Corpus moved from `163 / 0` relevant canonical / multi-listing canonical jobs to `156 / 7`.

Final production audit:
- `duplicate_candidates_high=0`
- `duplicate_candidates_blocked=1`
- `duplicate_candidates_medium=6`

Blocked teampool 163/168 remains split because source locations conflict (`Wien` vs `Wels`). Medium TSMG/Austro Holding/Trenkwalder/Anton Paar candidates remain untouched.

Canonical dedupe is intentionally closed for the current corpus.

## Normalized job concepts

Dimensions: `role / domain / task / method / tool`.

Files:
- `app/jobs/concepts.py`
- `app/jobs/concept_catalog.py`
- `migrations/versions/0007_job_concepts.py`
- `scripts/normalize_job_concepts.py`
- `scripts/job_concept_persisted_audit.py`
- `tests/test_job_concepts.py`

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

### Production persisted state — v2

Migration `0007_job_concepts` is applied in production.

Persisted extractor remains `concept-seed-2026-08-28-v2` until the next production command:
- `156/156` relevant jobs matched
- `49` distinct concepts
- `747` evidence rows
- `219 primary / 528 context`
- `invalid_scope_values=-`
- only v2 deterministic evidence is persisted

### Extractor v3 — validated, ready to persist

Current code extractor: `concept-seed-2026-08-28-v3`.

V3 is intentionally narrow and exists only because live fit ranking exposed missing primary identity evidence:
- new neutral `domain:electronics`;
- `Elektronik`, `Electronics`, `Hardware Engineer`, `Hardware Design Engineer` -> electronics;
- explicit `E-Konstrukteur`, `Elektrokonstrukteur`, `Electrical Design Engineer`, `EMC Engineer`, `EMV-Ingenieur` -> electrical-engineering;
- EPLAN tool alone still does **not** imply electrical domain.

Validated read-only v3 concept preview on all 156 jobs:
- `jobs_with_concepts=156`
- `jobs_without_concepts=0`
- `distinct_concepts_matched=50`
- `evidence_rows=780`
- `evidence_primary=228`
- `evidence_context=552`
- `domain:electronics`: 27 jobs, primary=6, context=24
- `domain:electrical-engineering`: 40 jobs, primary=7, context=38

V3 normalization is approved for production persistence.

## Candidate concept preferences / fit — validation closed

Files:
- `app/jobs/candidate_fit.py`
- `app/jobs/candidate_profile_seed.py`
- `app/jobs/candidate_profile_store.py`
- `migrations/versions/0008_candidate_preferences.py`
- `scripts/candidate_fit_audit.py`
- `scripts/sync_candidate_profile.py`
- `tests/test_candidate_fit.py`
- `tests/test_candidate_profile_sync.py`

Four states: `can_want / can_not_want / cannot_want / cannot_not_want`.

Absence of a preference row means **unrated**. Candidate profiles are first-class. `Job.job_fit_score` is not source of truth and remains untouched by audits.

Current seed: `candidate-profile-2026-08-28-v2`, 24 rated concepts. `domain:electrical-engineering` and `domain:electronics` are `cannot_not_want`. Generic `designer-engineer` and uncertain tools/roles/domains remain unrated.

### Fit policy v3 — validated

Current policy: `candidate-fit-2026-08-28-v3`.

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

Positive evidence budget `3.0` prevents one generic positive concept from saturating to 100.

Primary hard incompatibility rule:
- primary evidence;
- kind is `role` or `domain`;
- state is `cannot_not_want`;
- result exposes `hard_constraint` and score is capped at `25`.

Context-only incompatible mentions never create hard constraints. Transferable positive contributions remain visible even when a hard incompatibility caps the final score. Future recommender can filter hard constraints independently from the numeric score.

### Final read-only v3 fit preview — accepted

On all 156 relevant jobs:
- `jobs_scored=141`
- `jobs_unscored=15`
- `jobs_hard_incompatible=13`
- `score_mean=61.14`
- `score_median=63.00`
- `preference_coverage_mean=0.586`
- `preference_coverage_median=0.521`

Mechanical top remained stable and clean. Top examples:
- #144 Mechanical Design Engineer / Product Development -> 100
- #131 Fahrzeugbau / Mechanical Engineer -> 95
- #251 Maschinenbau/KFZ Entwicklungsingenieur -> 94
- #163/#168 Junior Konstrukteur Maschinenbau -> 93
- #221 Entwicklungsingenieur Maschinenbau -> 90
- #205 Senior Konstrukteur Maschinenbau -> 90
- #26 Konstrukteur Maschinenbau -> 90

Exactly 13 primary electrical/electronics jobs became hard-incompatible:
- #15 Head of Electronics
- #21 EMC Engineer
- #28 Entwicklungsingenieur Elektrotechnik
- #50 Labortechniker Elektronik
- #59 Staff Hardware Engineer
- #72/#73 Hardware Design Engineer
- #89 Electrical Engineer
- #128 E-Konstrukteur
- #213 Konstrukteur Elektrotechnik
- #215 E-Konstrukteur Energieinfrastruktur
- #254 Entwicklungsingenieur Elektrotechnik
- #259 Elektronik-Entwicklungsingenieur

All are `hard_incompatible=yes` and score `<=25` (pure incompatible examples #128/#213 naturally score 0).

Control jobs #80 Toyota Servicetechniker and #82 Field Service Manager have only context electronics/electrical evidence and correctly remain `hard_incompatible=no` with score 32.

Fit policy tuning is now considered **closed** unless later real user feedback demonstrates a generic semantic failure.

## Candidate preference persistence safety

Migration `0008_candidate_preferences` has **not** been applied yet and was refined before first production use.

`CandidateConceptPreference` now stores:
- `source = seed | manual`
- nullable `seed_version`

Safety semantics:
- bootstrap creates `source=seed` rows;
- future admin edits must mark the row `source=manual`;
- seed synchronization may update only `source=seed` rows;
- manual rows are never overwritten by bootstrap;
- stale seed-managed rows may be removed when the versioned seed intentionally stops rating a concept.

`app/jobs/candidate_profile_store.py` is the reusable service layer for this behavior. `scripts/sync_candidate_profile.py` is a thin read-only-by-default CLI around the same service. The future German admin UI should call the service layer rather than shelling out.

Regression test proves:
- first seed creates all 24 preferences;
- repeated seed is idempotent;
- converting a preference to `source=manual` and changing its state survives later seed synchronization.

CI #451 passes Ruff, Compile and the full test suite after this service-layer/provenance work.

## Immediate production sequence

1. Pull latest `bootstrap/austria-mvp`.
2. Persist validated v3 normalization:
   `python scripts/normalize_job_concepts.py --apply`
3. Immediately run persisted concept audit and verify expected v3 counts (`780`, `228/552`, only v3 deterministic evidence).
4. Run `candidate_fit_audit.py` **without** preview and verify it matches the accepted v3 preview (`141 scored`, `15 unscored`, `13 hard-incompatible`, stable top/bottom).
5. Only after that, apply migration `0008_candidate_preferences`.
6. Run `python scripts/sync_candidate_profile.py --apply`.
7. Run the same script without `--apply` and verify:
   - 24 persisted preferences;
   - source counts `seed:24` initially;
   - seed version `candidate-profile-2026-08-28-v2:24`;
   - no missing/mismatched/stale/manual override rows.
8. Then build German admin UI for concept/profile rating and recomputable/materialized fit.
9. After intrinsic fit UI is stable, combine with PostGIS job/property distance, salary and final recommendation ranking.
