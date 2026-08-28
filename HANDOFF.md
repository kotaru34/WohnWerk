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

Files:

- `app/jobs/dedupe.py`
- `scripts/job_duplicate_audit.py`
- `tests/test_job_dedupe.py`
- `app/jobs/merge.py`
- `scripts/merge_duplicate_jobs.py`
- `tests/test_job_merge.py`

### First production merge batch

Pre-merge refined state:

- `relevant_canonical_jobs=163`
- `already_multi_listing_canonical_jobs=0`
- `duplicate_candidates_high=8`
- `duplicate_candidates_medium=8`

Seven explicit fail-closed groups were applied successfully:

- 131/225 — PEISCHL Fahrzeugbau, survivor 131.
- 136/240 — Global Hydro, survivor 136.
- 155/255 — IVM Technical Consultants, survivor 155.
- 157/227 — Trenkwalder E-Plan, survivor 157.
- 159/206 — APS Group, survivor 159.
- 165/208 — Trenkwalder Klagenfurt, survivor 165.
- 251/252 — Oberaigner German/English StepStone variants, survivor 251.

Observed post-merge state matched prediction exactly:

- `relevant_canonical_jobs=156`
- `already_multi_listing_canonical_jobs=7`

The final read-only production audit then confirmed:

- `duplicate_candidates_high=0`
- `duplicate_candidates_blocked=1`
- `duplicate_candidates_medium=6`

Blocked pair is teampool 163/168: same-source title/body evidence is strong but explicit source locations conflict (`Wien` vs `Wels`). Medium cases include TSMG 3/4, Austro Holding 34/228, Trenkwalder generic `Konstrukteur` edges around 164/165/169, and Anton Paar 67/68. Leave all blocked/medium pairs untouched absent stronger evidence.

### Merge safety / cleanup

- known different normalized companies are a hard conflict;
- generic titles are conservative;
- cross-board exact company/title/location is strong syndication evidence;
- same-source distinct listing IDs are possible parallel openings;
- same-source non-generic needs description similarity >=0.82 for high evidence;
- same-source generic/template needs >=0.95;
- conflicting normalized companies or salary bundles block merge;
- same-source explicit location disagreement blocks merge;
- `--apply` is always required;
- all source `JobListing` rows/raw payloads are preserved on the survivor;
- equivalent locations are deduplicated and richer canonical data retained.

The first apply batch exposed an SQLAlchemy double-delete warning for equivalent `JobLocation` rows. Current code removes duplicate children through the relationship and lets `delete-orphan` own deletion, removing the warning path without changing merge semantics.

Audit now reports raw-high-but-unsafe pairs as `blocked` by running the same fail-closed merge plan used for mutation.

Canonical dedupe is intentionally considered closed for the current corpus.

## Normalized job concepts — current primary work

Goal: separate source wording from candidate preference/fit by normalizing every relevant canonical job into concepts before assigning any can/want score.

Dimensions:

- `role`
- `domain`
- `task`
- `method`
- `tool`

New files:

- `app/jobs/concepts.py` — ORM vocabulary/alias/evidence models.
- `app/jobs/concept_catalog.py` — deterministic seed vocabulary + phrase extractor.
- `migrations/versions/0007_job_concepts.py` — vocabulary/evidence tables.
- `scripts/normalize_job_concepts.py` — read-only dry-run by default; `--apply` seeds vocabulary and recomputes current-version evidence.
- `tests/test_job_concepts.py` — normalization/extraction regressions.
- `migrations/env.py` imports concept models so Alembic metadata remains complete.

### Data model

`JobConcept`:

- canonical `kind + slug` identity;
- German display label `label_de`;
- enabled flag.

`JobConceptAlias`:

- many surface forms per concept;
- normalized alias;
- optional language;
- seed/manual provenance;
- enabled flag.

`JobConceptEvidence`:

- `job_id` + `concept_id`;
- matched alias;
- source field (`title` / `description`);
- confidence;
- explicit extractor version.

Evidence is recomputable and candidate-independent. Candidate preferences must be attached to canonical concepts later, not raw words.

### Extractor v1

Current extractor version: `concept-seed-2026-08-28-v1`.

It is intentionally deterministic phrase matching first, not an LLM. Text is Unicode/case/punctuation normalized and aliases use word boundaries. This preserves inspectable evidence and avoids the earlier class of substring bugs such as `FEM` matching `female`.

Initial vocabulary covers mechanical roles/domains/tasks/methods/tools plus explicit electrical-engineering evidence, including examples such as:

- roles: Maschinenbauingenieur, mechanischer Konstrukteur, Entwicklungsingenieur, Projektingenieur, technischer Projektleiter, Service Engineer, CAD-Konstrukteur;
- domains: Maschinenbau, Fahrzeugbau/Automotive, Sonderfahrzeugbau, Schienenfahrzeugtechnik, Sondermaschinenbau, Wasserkraft, Elektrotechnik;
- tasks: mechanische Konstruktion, Produktentwicklung, Anforderungen/Lasten-/Pflichtenhefte, Lieferantenkoordination, Versuch/Validierung, Montage/Inbetriebnahme, Berechnung/Simulation, technische Projektsteuerung, Teamführung, technische Dokumentation;
- methods: FEM, FMEA, agile development/Scrum;
- tools: SolidWorks, CATIA, Creo, Siemens NX, Inventor, AutoCAD, EPLAN.

Important design choice: the Python seed is only bootstrap. `--apply` seeds missing vocabulary/aliases but extraction then reads enabled concepts/aliases back from the DB. Future admin UI edits can therefore change synonyms without modifying Python code. Existing disabled aliases are not forcibly re-enabled by seeding.

CI #401 passed Ruff, Compile and the full test suite for this first normalization slice.

## Immediate work order

1. Pull current `bootstrap/austria-mvp`.
2. Do **not** run migration `0007` yet.
3. Run only the read-only concept coverage audit:
   `python scripts/normalize_job_concepts.py --unmatched-limit 50`
4. Inspect coverage counts, top concepts and unmatched titles against the real 156-job corpus.
5. Tighten/expand the generic concept vocabulary only from real corpus evidence; avoid candidate preference scoring at this stage.
6. Once dry-run coverage is acceptable, apply `alembic upgrade head` and then run `python scripts/normalize_job_concepts.py --apply`.
7. After persisted concept evidence is validated, add candidate concept preferences using the four-state model: can+want / can+not-want / cannot+want / cannot+not-want.
8. Then compute intrinsic job fit independent of geography, followed by PostGIS house/job distance and final recommendation ranking.
