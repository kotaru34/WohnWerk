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

## User-directed acquisition model

Consumer-board acquisition should behave like a person quickly scanning vacancies:

- a handful of broad/focused searches;
- first result page initially;
- stable-ID dedupe;
- details only when useful and title looks interesting;
- sequential low-rate requests;
- no whole-site crawl, aggressive pagination or reconciliation for these frontiers;
- ToS text can inform priority but is advisory rather than an architecture blocker by itself;
- no technical anti-bot bypass.

Do not return to the earlier permission-first/purge detour. Adzuna/Jooble are supplementary APIs, not replacements for normal boards.

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

Seven explicit fail-closed groups were applied successfully. Corpus moved from:

- `relevant_canonical_jobs=163`
- `already_multi_listing_canonical_jobs=0`

to:

- `relevant_canonical_jobs=156`
- `already_multi_listing_canonical_jobs=7`

Final production audit:

- `duplicate_candidates_high=0`
- `duplicate_candidates_blocked=1`
- `duplicate_candidates_medium=6`

Blocked pair is teampool 163/168: strong same-source title/body evidence but explicit locations conflict (`Wien` vs `Wels`). Medium TSMG/Austro Holding/Trenkwalder/Anton Paar candidates remain untouched.

Merge engine remains explicit-ID, dry-run by default and fail-closed on company/salary/evidence/same-source location conflicts. All source listings/raw payloads survive on canonical survivors. The SQLAlchemy duplicate-location double-delete warning was removed by letting relationship `delete-orphan` own child deletion. Audit and merge safety now use the same plan.

Canonical dedupe is intentionally considered closed for the current corpus.

## Normalized job concepts — current primary work

Goal: normalize source wording into candidate-independent concepts before any can/want scoring.

Dimensions:

- `role`
- `domain`
- `task`
- `method`
- `tool`

Files:

- `app/jobs/concepts.py` — canonical concept, alias and evidence ORM models.
- `app/jobs/concept_catalog.py` — deterministic seed vocabulary + phrase extractor.
- `migrations/versions/0007_job_concepts.py` — vocabulary/evidence tables.
- `scripts/normalize_job_concepts.py` — read-only by default; `--apply` seeds/recomputes.
- `tests/test_job_concepts.py` — normalization/extraction regressions.
- `migrations/env.py` imports concept models for complete Alembic metadata.

### Data model

`JobConcept` stores canonical `kind + slug`, German label and enabled state.

`JobConceptAlias` stores many surface forms per concept with normalized alias, optional language, provenance and enabled state.

`JobConceptEvidence` stores job/concept, matched alias, source field (`title` / `description`), confidence and extractor version.

Evidence is recomputable and candidate-independent. Candidate preferences belong on canonical concepts later, never raw source words.

### Production dry-run v1

Extractor v1 (`concept-seed-2026-08-28-v1`) was run read-only on the post-dedupe 156-job corpus:

- `relevant_active_jobs=156`
- `jobs_with_concepts=131`
- `jobs_without_concepts=25`
- `distinct_concepts_matched=32`
- `evidence_rows=433`
- `evidence_role=91`
- `evidence_domain=154`
- `evidence_task=114`
- `evidence_method=11`
- `evidence_tool=63`

Top raw evidence counts included:

- `domain:mechanical-engineering=71`
- `domain:electrical-engineering=42`
- `task:assembly-commissioning=36`
- `role:development-engineer=28`
- `domain:automotive=21`
- `task:product-development=19`
- `role:mechanical-designer=19`
- `task:testing-validation=18`
- `role:mechanical-engineer=17`
- `domain:special-machinery=17`
- `tool:solidworks=17`

The `42` electrical figure needs evidence inspection because v1 counted title and description evidence rows rather than unique jobs.

The 25 unmatched titles were highly structured rather than random. Most were variants of:

- `Maschinenbautechniker`
- generic `Konstrukteur` / `Senior Designer`
- `Service Techniker`
- `Berechnungsingenieur`
- `CAD-Techniker` / Detail-/Ausführungsplaner
- `Produktionsleiter`
- `Gebäudetechnik / HKLS`
- `Anlagenbau`
- `Stahlbau`
- `Mechatroniker`
- `Metalltechniker`
- `Schlosser / Maschinenschlosser`
- `Instandhaltung`

### Extractor v2

Current extractor version: `concept-seed-2026-08-28-v2`.

V2 expands only neutral professional normalization concepts observed in the real corpus. It does not encode candidate preference.

Added/expanded roles include:

- Maschinenbautechniker
- generic Konstrukteur / Design Engineer
- Berechnungsingenieur
- generic Projektleiter / Projektmanager
- Produktionsleiter
- spaced/hyphenated Service Techniker / Field Service Technician
- CAD-Techniker / Technischer Zeichner / Detailplaner / Ausführungsplaner
- Mechatroniker
- Metalltechniker
- Schlosser / Maschinenschlosser

Added domains include:

- Anlagenbau
- Stahlbau
- Gebäudetechnik / HKLS
- Mechatronik

Added tasks include:

- Instandhaltung
- Fertigung / Produktion
- Ausführungs-/Detailplanung
- Toleranzanalyse

Important semantic guard: generic `Konstrukteur` maps to a generic designer role but does **not** imply the `mechanical-engineering` domain. Mechanical domain still requires separate mechanical evidence. EPLAN likewise remains only a tool unless explicit electrical wording is present.

The audit summary now distinguishes unique-job coverage from evidence-row counts:

- `jobs_role/domain/task/method/tool`
- per-concept `jobs=`, `title=` and `description=` counts

The script also supports repeatable targeted evidence inspection:

`--audit-concept KIND:SLUG`

with `--audit-limit` controlling printed jobs.

Deterministic recompute deletes all prior `concept-seed-*` evidence before inserting the current version, so future v3/v4 runs cannot accumulate stale deterministic evidence. Other extractor families remain untouched.

Seed vocabulary is bootstrap only. Applied extraction reads enabled concepts/aliases back from the DB, allowing later admin UI synonym edits/disablement without Python changes.

CI #406 passed Ruff, Compile and the full test suite for v2 vocabulary, improved audit reporting and stale deterministic evidence replacement.

## Immediate work order

1. Pull current `bootstrap/austria-mvp`.
2. Do **not** run migration `0007` yet.
3. Run v2 read-only coverage + targeted evidence audit:

   `python scripts/normalize_job_concepts.py --unmatched-limit 50 --audit-concept domain:electrical-engineering --audit-concept role:mechanical-technician --audit-concept role:designer-engineer --audit-limit 50`

4. Inspect:
   - overall matched/unmatched coverage;
   - unique jobs per concept vs title/description evidence;
   - whether electrical-engineering examples are genuine explicit electrical mentions;
   - whether new generic designer/technician concepts create obvious false positives.
5. Refine only from actual evidence. Do not mix candidate preference into normalization.
6. Once coverage/precision is healthy, apply `alembic upgrade head`, then `python scripts/normalize_job_concepts.py --apply`.
7. Validate persisted evidence.
8. Add four-state candidate concept preferences: can+want / can+not-want / cannot+want / cannot+not-want.
9. Compute intrinsic fit independently of geography, then combine with PostGIS house/job distance, salary and final recommendation ranking.
