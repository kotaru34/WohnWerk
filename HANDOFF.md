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
- keep requests sequential and slow enough to avoid hammering the service;
- no pagination/reconciliation unless later justified by a concrete need;
- terms-of-service text is advisory for source prioritization, not an architecture blocker by itself;
- do not perform technical anti-bot bypasses.

Consumer job boards are therefore valid low-impact sources when normal public pages work without bypasses.

## karriere.at frontier — restored

Files:

- `app/sources/job/karriere_at.py`
- `scripts/run_karriere_at_jobs.py`
- `tests/test_karriere_at_job_source.py`

Behavior:

- five focused first-page searches;
- numeric `/jobs/<id>` stable identity;
- cross-query dedupe;
- cheap title prefilter before details;
- max 8 detail pages/query;
- sequential global delay (0.65 s default);
- no reconciliation; always coverage-incomplete.

Historical production #38:

- 5/5 shards, 35 HTTP requests total;
- 30 relevant jobs / 30 new;
- no source or rate-limit failures;
- 27 structured salaries;
- 27 geo-resolved relevant locations.

The 30 prototype rows were later purged during a temporary strategy detour. Purge was safe: `shared_jobs=0`, so no shared canonical Jobs were damaged. The runner is now restored and will re-enable/repopulate the source on the next run.

## jobs.at frontier — restored and broadened

Files:

- `app/sources/job/jobs_at.py`
- `scripts/run_jobs_at_jobs.py`
- `tests/test_jobs_at_job_source.py`

Historical production #39:

- 5/5 shards, 11 HTTP requests total;
- 6 relevant jobs / 6 new;
- no source failures;
- 4 structured salaries.

Those 6 prototype rows were also safely purged with `shared_jobs=0` and no shared canonical damage.

The restored runner now uses broader human-style searches while keeping the same tiny request budget:

- `Maschinenbau`
- `Konstrukteur`
- `CAD Konstrukteur`
- `Mechanischer Konstrukteur`
- `SolidWorks`

Each shard still reads one search page and opens at most 8 detail pages after title filtering. No reconciliation.

Run #39 also exposed two future cleanup items:

- title prefilter should reject `E-Plan` spelling, not only `Eplan`;
- generic structured locations such as `AT, Österreich` can be less useful than a visible page location; prefer the more specific source-backed location when available.

These are parser improvements, not reasons to stop the source.

## StepStone Austria — new search-card-only frontier

Files:

- `app/sources/job/stepstone_at.py`
- `scripts/run_stepstone_at_jobs.py`
- `tests/test_stepstone_at_job_source.py`

This is even lighter than karriere/jobs.at:

- five search pages total;
- **zero detail-page requests**;
- search cards already provide title, company, location/PLZ and a substantial snippet;
- stable numeric ID parsed from `/stellenangebote--...--<id>-inline.html`;
- explicit `1030 Wien`-style locations preserve `postal_code=1030`;
- regional labels remain non-postal and are not fabricated into PLZ;
- cross-query ID dedupe;
- always coverage-incomplete / no disappearance authority.

Current searches:

- Konstrukteur Maschinenbau
- Maschinenbauingenieur
- Mechanical Engineer
- Entwicklungsingenieur Maschinenbau
- Projektingenieur Maschinenbau

CI #335 passed Ruff, Compile and the full test suite for this implementation.

## Broad API aggregators — supplementary bonus layer

Adzuna Austria and Jooble Austria adapters were also implemented during the source-strategy detour. Keep them: they are useful extra corpus sources, but they do **not** replace the large human-facing boards.

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

Adzuna + Jooble + purge safety passed CI #330.

## Prototype purge utility

`scripts/purge_job_source_listings.py` remains as a general maintenance tool, but **do not purge karriere.at or jobs.at again** under the current strategy.

The production purge already completed safely:

- karriere.at: 30 listings / 30 exclusive Jobs / shared_jobs=0 / deleted_jobs=30.
- jobs.at: 6 listings / 6 exclusive Jobs / shared_jobs=0 / deleted_jobs=6.

## Immediate production work order

1. Pull current branch and run tests.
2. Run `python scripts/run_karriere_at_jobs.py` once; no reconciliation.
3. Run `python scripts/run_jobs_at_jobs.py` once with the restored broad queries; no reconciliation.
4. Run `python scripts/run_stepstone_at_jobs.py` once; this should make exactly five search-page requests and zero detail requests.
5. Run location resolution.
6. Inspect stats/rejection audit/source health for all three boards.
7. Fix only generic parser issues exposed by those live runs (especially jobs.at E-Plan/location specificity and StepStone card parsing).
8. Then add willhaben Jobs using the same low-impact first-page model.
9. Keep Adzuna/Jooble and ATS feeds as supplementary independent sources.
10. At hundreds→thousands relevant jobs, move on to normalized concepts, German profile review, candidate fit and house/job recommendations.
