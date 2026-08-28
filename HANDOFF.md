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

Persisted extractor remains `concept-seed-2026-08-28-v2`:
- `156/156` relevant jobs matched
- `49` distinct concepts
- `747` evidence rows
- `219 primary / 528 context`
- `invalid_scope_values=-`
- only v2 deterministic evidence is persisted

Targeted persisted checks:
- `domain:electrical-engineering`: 40 jobs, primary=4, context=38
- `role:mechanical-technician`: 23 jobs, primary=21, context=8
- `role:designer-engineer`: 48 jobs, primary=44, context=32

### Extractor v3 — code/preview only, not yet persisted

Current code extractor: `concept-seed-2026-08-28-v3`.

V3 is intentionally narrow and was added only because live fit ranking demonstrated missing identity evidence:
- new neutral `domain:electronics`;
- `Elektronik`, `Electronics`, `Hardware Engineer`, `Hardware Design Engineer` -> electronics;
- explicit `E-Konstrukteur`, `Elektrokonstrukteur`, `Electrical Design Engineer`, `EMC Engineer`, `EMV-Ingenieur` -> electrical-engineering;
- EPLAN tool alone still does **not** imply electrical domain.

Read-only v3 concept preview on all 156 jobs:
- `jobs_with_concepts=156`
- `distinct_concepts_matched=50`
- `evidence_rows=780`
- `228 primary / 552 context`
- `domain:electronics`: 27 jobs, primary=6, context=24
- `domain:electrical-engineering`: 40 jobs, primary=7, context=38

Examples now correctly primary-classified:
- `Head of Electronics` -> electronics primary
- `Elektronik-Entwicklungsingenieur` -> electronics primary
- `Staff Hardware Engineer` / `Hardware Design Engineer` -> electronics primary
- `EMC Engineer` -> electrical-engineering primary
- `E-Konstrukteur` -> electrical-engineering primary

V3 is not persisted yet. Use `candidate_fit_audit.py --preview-current-extractor` for read-only fit evaluation until explicitly approved.

## Candidate concept preferences / fit — current primary work

Files:
- `app/jobs/candidate_fit.py`
- `app/jobs/candidate_profile_seed.py`
- `migrations/versions/0008_candidate_preferences.py`
- `scripts/candidate_fit_audit.py`
- `tests/test_candidate_fit.py`

Four states: `can_want / can_not_want / cannot_want / cannot_not_want`.

Absence of a preference row means **unrated**. Candidate profiles are first-class. `Job.job_fit_score` is not source of truth and remains untouched by audits.

Current seed: `candidate-profile-2026-08-28-v2`, 24 rated concepts. `domain:electrical-engineering` and `domain:electronics` are `cannot_not_want`. Generic `designer-engineer` and uncertain tools/roles/domains remain unrated.

### Fit policy evolution

Policy v1 exposed a positive-saturation bug: one positive generic role/domain could normalize to 100.

Policy v2 (`candidate-fit-2026-08-28-v2`) added:
- state values: can+want `+1.00`, can+not-want `-0.20`, cannot+want `+0.20`, cannot+not-want `-1.00`;
- kind weights: role `1.15`, domain `1.25`, task `1.00`, method/tool `0.75`;
- scope amplitude: primary `1.00`, context `0.35`;
- positive evidence budget `3.0`, so one attractive concept cannot saturate.

Approximate positive behavior:
- one primary role -> ~69
- one primary domain -> ~71
- primary role + domain -> ~90
- role + domain + task can reach 100

V2 live v3-extractor preview produced:
- `jobs_scored=141`, `jobs_unscored=15`
- mean `62.41`, median `63.00`
- top ranking became cleanly mechanical: Mechanical Design/Product Development, Fahrzeugbau, Maschinenbau/KFZ, Konstrukteur Maschinenbau, etc.
- false electronics/electrical jobs moved down strongly.

However one remaining semantics problem was demonstrated: `Elektronik-Entwicklungsingenieur ... Produktentwicklung` still scored 63 because primary `electronics=cannot_not_want` was only one weighted vote against positive transferable role/task evidence.

### Fit policy v3 — current code

Current policy: `candidate-fit-2026-08-28-v3`.

New rule: **primary hard incompatibility**.

If a primary evidence concept is:
- kind `role` or `domain`, and
- candidate state `cannot_not_want`,

then `JobFitResult` exposes it as a `hard_constraint` and score is capped at `25`.

Important semantics:
- transferable positive contributions are still preserved and visible;
- context-only `cannot_not_want` never creates a hard constraint;
- pure primary incompatible jobs can still naturally score 0;
- future recommender can filter `hard_constraints` independently of score instead of inferring rejection from a numeric threshold.

`candidate_fit_audit.py` now prints:
- `jobs_hard_incompatible`
- hard constraint kinds and cap
- `hard_incompatible=yes/no` per job
- exact `hard_constraints=` labels
- contribution scope in detailed job audits.

Regression tests cover:
- primary hard-incompatible domain with positive transferable role/task is capped at 25;
- pure primary incompatible domain remains 0;
- context-only incompatible domain remains attenuated and does not become hard;
- positive corroboration budget;
- multi-concept positive fit;
- unrated coverage;
- duplicate evidence collapsing to strongest signal.

CI #442 passed Ruff, Compile and the full suite for policy v3/hard constraints.

## Immediate work order

1. Pull latest `bootstrap/austria-mvp`.
2. **Do not apply migration 0008 yet.**
3. **Do not persist v3 normalization yet.**
4. Run one final read-only v3 fit preview with `--preview-current-extractor`.
5. Verify:
   - mechanical top ranking remains stable;
   - explicit primary electrical/electronics vacancies are `hard_incompatible=yes`;
   - #259/#254/#28/#72/#73 are <=25;
   - context-only electrical/electronics mentions are not hard-incompatible;
   - hard-incompatible count is plausible for the corpus.
6. If clean, persist v3 with `normalize_job_concepts.py --apply` and immediately run persisted concept audit.
7. Re-run fit audit from persisted v3 evidence and confirm it matches preview.
8. Apply migration `0008_candidate_preferences` and persist candidate profile/preferences.
9. Build German admin UI for four-state concept/profile rating and recomputable/materialized fit.
10. Then combine intrinsic fit with PostGIS house/job distance, salary and final recommendation ranking.
