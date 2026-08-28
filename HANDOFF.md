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

Candidate is fundamentally mechanical/Maschinenbau, not electrical. Future fit should strongly prefer mechanical CAD/construction, components/assemblies, automotive/special-vehicle/rail work, product development, technical project work, supplier coordination and mechanically relevant validation/testing. Pure electrical engineering is future fit `cannot + not want`; this affects candidate fit, not broad acquisition.

## Canonical job dedupe — closed for current corpus

Seven explicit fail-closed groups were applied successfully. Corpus moved from `163 / 0` relevant canonical / multi-listing canonical jobs to `156 / 7`.

Final production audit:
- `duplicate_candidates_high=0`
- `duplicate_candidates_blocked=1`
- `duplicate_candidates_medium=6`

Blocked pair is teampool 163/168: strong same-source title/body evidence but explicit source locations conflict (`Wien` vs `Wels`). Medium TSMG/Austro Holding/Trenkwalder/Anton Paar candidates remain untouched.

Merge engine remains explicit-ID, dry-run by default and fail-closed on company/salary/evidence/same-source location conflicts. Source listings/raw payloads survive on canonical survivors. The SQLAlchemy duplicate-location double-delete warning was removed by letting relationship `delete-orphan` own child deletion. Audit and merge safety share the same plan.

Canonical dedupe is intentionally closed for the current corpus.

## Normalized job concepts — current primary work

Goal: normalize source wording into candidate-independent concepts before any can/want scoring.

Dimensions:
- `role`
- `domain`
- `task`
- `method`
- `tool`

Files:
- `app/jobs/concepts.py` — canonical concept, alias, evidence models and evidence semantics.
- `app/jobs/concept_catalog.py` — deterministic seed vocabulary + phrase extractor.
- `migrations/versions/0007_job_concepts.py` — vocabulary/evidence tables.
- `scripts/normalize_job_concepts.py` — read-only by default; `--apply` seeds/recomputes.
- `tests/test_job_concepts.py` — normalization/extraction/evidence regressions.
- `migrations/env.py` imports concept models for complete Alembic metadata.

### Data model

`JobConcept` stores canonical `kind + slug`, German label and enabled state.

`JobConceptAlias` stores many surface forms per concept with normalized alias, optional language, provenance and enabled state.

`JobConceptEvidence` stores job/concept, matched alias, source field, semantic scope, confidence and extractor version.

Evidence is recomputable and candidate-independent. Candidate preferences belong on canonical concepts later, never raw source words.

### Extractor v1 result

Read-only v1 on the post-dedupe 156-job corpus:
- `jobs_with_concepts=131`
- `jobs_without_concepts=25`
- `distinct_concepts_matched=32`
- `evidence_rows=433`

The 25 unmatched titles were mainly systematic variants such as Maschinenbautechniker, generic Konstrukteur/Senior Designer, Service Techniker, Berechnungsingenieur, CAD-Techniker, Anlagenbau, Stahlbau, Mechatroniker, Metalltechniker, Schlosser and Instandhaltung.

### Extractor v2 vocabulary

Current phrase extractor version remains `concept-seed-2026-08-28-v2` because v2 has never been persisted; the latest changes refine evidence semantics rather than phrase matching.

V2 adds only neutral concepts observed in production, including:

Roles:
- Maschinenbautechniker
- generic Konstrukteur / Design Engineer
- Berechnungsingenieur
- generic Projektleiter / Projektmanager
- Produktionsleiter
- Service Techniker / Field Service Technician
- CAD-Techniker / Technischer Zeichner / Detailplaner / Ausführungsplaner
- Mechatroniker
- Metalltechniker
- Schlosser / Maschinenschlosser

Domains:
- Anlagenbau
- Stahlbau
- Gebäudetechnik / HKLS
- Mechatronik

Tasks:
- Instandhaltung
- Fertigung / Produktion
- Ausführungs-/Detailplanung
- Toleranzanalyse

Guardrails:
- generic `Konstrukteur` is a generic designer role but does not imply mechanical-engineering;
- EPLAN alone does not imply electrical-engineering;
- word boundaries keep FEM from matching `female`;
- deterministic recompute deletes prior `concept-seed-*` evidence while leaving future other extractor families untouched;
- DB-enabled concepts/aliases drive applied extraction, so future German admin UI edits do not require Python changes.

### Production v2 precision audit

Read-only v2 on the real 156-job corpus produced:
- `jobs_with_concepts=156`
- `jobs_without_concepts=0`
- `distinct_concepts_matched=49`
- `evidence_rows=747`
- `jobs_role=115`, `evidence_role=229`
- `jobs_domain=125`, `evidence_domain=268`
- `jobs_task=86`, `evidence_task=176`
- `jobs_method=11`, `evidence_method=11`
- `jobs_tool=38`, `evidence_tool=63`

Important precision observations:

1. `role:mechanical-technician` is clean and mostly primary identity evidence:
   - 23 jobs total;
   - 21 have title evidence;
   - examples are actual Maschinenbautechniker title variants.

2. `role:designer-engineer` is intentionally generic:
   - 48 jobs;
   - 44 have title evidence;
   - includes mechanical, electrical, civil/HKLS and hardware design roles;
   - therefore this concept must not itself imply positive mechanical fit. Domain/task evidence decides specialization.

3. `domain:electrical-engineering` exposed the limit of raw phrase matching:
   - 40 unique jobs;
   - only 4 title-primary matches;
   - 38 description matches;
   - many description matches are explicit `Elektrotechnik` / `Electrical Engineering` mentions in education/qualification/context, not proof that the vacancy itself is primarily electrical.

Examples include mechanical/service/development titles whose descriptions mention Elektrotechnik as one accepted background. Conversely titles such as `Entwicklungsingenieur Elektrotechnik`, `Electrical Engineer` and `Konstrukteur*in Elektrotechnik` are genuine primary electrical identity evidence.

### Primary vs context evidence semantics

Because phrase occurrence in a description is not equivalent to job identity, evidence now has explicit `scope`:

- title matches -> `scope=primary`, confidence `1.00`;
- description role matches -> `scope=context`, confidence `0.45`;
- description domain matches -> `scope=context`, confidence `0.55`;
- description task matches -> `scope=context`, confidence `0.80`;
- description method matches -> `scope=context`, confidence `0.85`;
- description tool matches -> `scope=context`, confidence `0.85`.

This preserves useful context without letting requirements such as `Studium Maschinenbau, Mechatronik oder Elektrotechnik` redefine the vacancy as three primary domains.

Migration `0007` was updated before production application to persist the non-null `scope` field and index it.

Audit output now prints `primary/context` counts and targeted concept evidence includes field/scope/confidence.

CI #412 passed Ruff, Compile and the full test suite for evidence scope/confidence semantics and migration wiring.

## Immediate work order

1. Pull current `bootstrap/austria-mvp`.
2. Apply migration `0007` with `alembic upgrade head`.
3. Run `python scripts/normalize_job_concepts.py --apply` to seed the DB vocabulary and persist current deterministic evidence.
4. Immediately run a read-only concept audit again and verify:
   - 156 relevant jobs still present;
   - persisted evidence count is 747 unless DB alias state intentionally differs from seed;
   - electrical description mentions are persisted as `context/0.55`, not primary;
   - title identity matches are primary/1.00.
5. Then add four-state candidate concept preferences: can+want / can+not-want / cannot+want / cannot+not-want.
6. Intrinsic job fit must weight primary identity more strongly than context and remain independent of geography.
7. Then combine fit with PostGIS house/job distance, salary and final recommendation ranking.
