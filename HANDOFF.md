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
- Do not invent Austrian PLZ/location points; preserve provenance.
- Geography is separate from intrinsic fit; use PostGIS rather than permanent NxM pairs.
- No CAPTCHA bypass, credential theft, fingerprint spoofing or deliberate anti-bot evasion.

## Stable property acquisition

Do not reopen absent live regression:

- IMMMO #11: coverage OK, 13,948 seen, 1,167 pages, 9/9 shards, disappeared=0.
- s REAL #16: coverage OK, 314 seen, detail-enriched, disappeared=0.
- ImmoAds retired/disabled.

## Stable supplementary ATS job sources

### SmartRecruiters

Production #33 closed for correctness/liveness/republish identity:

- 15/15 shards, coverage OK, source_reported=411.
- 53 source-active listings / 42 relevant-active canonical jobs.
- 41/42 relevant locations resolved.

### Personio

Production #37 closed for correctness/calibration:

- DE + EN merged by stable position ID.
- 14/14 shards, 28 requests/pages, coverage OK.
- source_reported=215 without language doubling.
- 17 relevant-active canonical jobs.
- only unresolved relevant location: `österreichweit`.

Keep Personio supplementary. Do not manually enumerate employers as the main scaling model.

### Lever

Production #22 remains stable:

- 5/5 shards, coverage OK.
- 6 relevant active jobs.
- all relevant locations resolved.

Lever remains supplementary.

## Discovery gate v14

Current version: `profile-seed-2026-08-28-v14`.

Generic correctness is closed for now. v14 fixes FEM/`female` evidence while preserving real FEM/FEA/finite-element evidence. Candidate preference never belongs in discovery.

Candidate is fundamentally mechanical/Maschinenbau, not electrical. Future candidate fit should strongly prefer mechanical CAD/construction, components/assemblies, automotive/special-vehicle/rail work, product development, technical project work, supplier coordination and mechanically relevant validation/testing. Pure electrical engineering is explicit `cannot + not want` for candidate fit, not acquisition.

## PRIMARY job acquisition strategy — low-impact broad boards

User directive is authoritative for source behavior:

- behave like a person quickly scanning job titles;
- use a handful of broad/focused searches, not whole-site crawling;
- inspect only the first result page initially;
- deduplicate IDs before any details;
- open details only when actually needed and title looks relevant;
- keep requests sequential and low-rate;
- no pagination/reconciliation unless later justified by a concrete need;
- terms-of-service text is advisory for source prioritization, not an architecture blocker by itself;
- do not perform technical anti-bot bypasses.

## karriere.at frontier — production #40

Files:

- `app/sources/job/karriere_at.py`
- `scripts/run_karriere_at_jobs.py`
- `tests/test_karriere_at_job_source.py`

Production #40 after restoring the source:

- 5/5 shards, 0 failed;
- 35 HTTP requests total;
- 30 seen / 30 new;
- source-reported search counts sum to 435;
- all 30 passed discovery v14;
- 34 relevant locations, 27 geo-resolved, 7 unresolved;
- 27 structured salaries, 15 annualized;
- no source/rate-limit errors.

Interpretation: stable and useful. Do not deepen traversal yet.

## jobs.at broad frontier — production #41

Files:

- `app/sources/job/jobs_at.py`
- `scripts/run_jobs_at_jobs.py`
- `tests/test_jobs_at_job_source.py`

Broad searches:

- Maschinenbau
- Konstrukteur
- CAD Konstrukteur
- Mechanischer Konstrukteur
- SolidWorks

Production #41:

- 5/5 shards, 0 failed;
- only 18 HTTP requests;
- 13 seen / 13 new;
- all 13 passed discovery v14;
- 14 relevant locations, 7 geo-resolved;
- 12 structured salaries + 1 salary text;
- 3 salaries annualized.

This is materially better than old #39 (6 jobs / 11 requests) while remaining light.

Observed cleanup items:

- `E-Plan Konstrukteur` and `E-Planer` are acquisition-level electrical candidates. They can remain in the broad corpus; future candidate fit will push pure electrical roles down. If detail-request saving becomes worthwhile, extend the cheap prefilter to `E-Plan` spelling.
- structured location such as `AT, Österreich` is weak; prefer a more specific visible source location when available, but never invent a PLZ.

## StepStone Austria — production #42 + parser fix

Files:

- `app/sources/job/stepstone_at.py`
- `scripts/run_stepstone_at_jobs.py`
- `tests/test_stepstone_at_job_source.py`

Design:

- five search pages total;
- zero detail-page requests;
- stable numeric ID from `/stellenangebote--...--<id>-inline.html`;
- search cards provide title/company/location and often a useful snippet;
- explicit PLZ preserved when present;
- always coverage-incomplete / no disappearance authority.

Production #42 exposed one concrete source-markup variant:

- 3/5 shards succeeded;
- 3 jobs inserted;
- `entwicklungsingenieur-maschinenbau` and `konstrukteur-maschinenbau` failed with PostgreSQL `StringDataRightTruncation` on a `VARCHAR(500)` field.

Root cause: some StepStone result cards wrap most/all card content inside the job `<a>`. The first parser joined all anchor text and accidentally made title = title + company + location + description.

Fix now committed and covered by regression test:

- first anchor text node is title;
- remaining anchor text becomes normal card tail;
- source title/company/location have conservative length sanity guards;
- long description remains `Text` rather than contaminating short fields;
- regression fixture includes a whole-card anchor with >500-char description and explicit `6330 Kufstein`.

CI #338 passed Ruff, Compile and full tests after the fix.

**Next production action for StepStone:** rerun only `python scripts/run_stepstone_at_jobs.py`; do not rerun karriere/jobs.at just for this fix.

## willhaben Jobs — implemented, awaiting first live probe

Files:

- `app/sources/job/willhaben_jobs.py`
- `scripts/run_willhaben_jobs.py`
- `tests/test_willhaben_job_source.py`

Current frontier:

- Konstrukteur Maschinenbau
- Maschinenbau
- Konstrukteur
- CAD Zeichner
- Entwicklungsingenieur:in

Behavior:

- five first-page search requests total;
- zero detail-page requests;
- stable numeric ID from `/jobs/job/<slug>/<id>`;
- search card parses title, company, publication label and location;
- strips displayed company suffix ` Jobs`;
- understands multi-employment metadata such as `Teilzeit, Vollzeit, Wien, 01. Bezirk...` without throwing away location components;
- explicit `9020 Klagenfurt...` preserves PLZ;
- whole-card-inside-anchor variant is handled like StepStone so long snippets cannot become titles;
- always coverage-incomplete / no disappearance authority.

CI #341 passed Ruff, Compile and the full test suite for willhaben.

First live probe should be exactly five requests and zero details.

## Broad API aggregators — supplementary bonus layer

Adzuna Austria and Jooble Austria remain implemented as extra corpus sources, not replacements for human-facing boards.

### Adzuna

- `app/sources/job/adzuna.py`
- `scripts/run_adzuna_jobs.py`
- five API queries/run, no advertiser-page crawl;
- credentials from `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` only;
- predicted salary marked estimated;
- coverage-incomplete.

### Jooble

- `app/sources/job/jooble.py`
- `scripts/run_jooble_jobs.py`
- five API queries/run, no detail crawl;
- key from `JOOBLE_AT_API_KEY` only;
- salary kept as source text when period semantics are unclear;
- coverage-incomplete.

## Prototype purge utility

`scripts/purge_job_source_listings.py` remains as a general maintenance tool, but **do not purge karriere.at or jobs.at again** under the current strategy.

Historical temporary purge completed safely with `shared_jobs=0`; production #40/#41 have since repopulated both sources.

## Immediate production work order

1. Pull current branch and run tests.
2. Rerun StepStone only: `python scripts/run_stepstone_at_jobs.py`.
3. Run willhaben once: `python scripts/run_willhaben_jobs.py`.
4. Resolve locations.
5. Inspect stats/rejection audit/source health for StepStone + willhaben.
6. Fix only generic parser issues exposed by those two live probes.
7. Keep karriere.at/jobs.at running as stable low-impact frontiers; no reconciliation.
8. Keep Adzuna/Jooble and ATS feeds as supplementary independent sources.
9. Once broad corpus reaches hundreds→thousands relevant jobs, shift primary effort to normalized concepts, German profile review, candidate fit and house/job recommendations.
