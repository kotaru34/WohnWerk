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
- Professional-neighbourhood relevance is independent in `raw_payload["wohnwerk_discovery_gate"]`.
- Application liveness/freshness is independent from source lifecycle and relevance.
- Candidate fit/preferences are independent and recomputable.
- Gate/taxonomy changes must never masquerade as source disappearance.
- Failed/partial reconciliation never mass-deactivates.
- Canonical jobs deactivate only when none of their source listings remains active.
- Do not invent Austrian PLZ/location points; approximate geography keeps provenance.
- Geography is separate from intrinsic job fit; use PostGIS rather than permanent NxM pairs.
- No CAPTCHA bypass, credential theft, fingerprint spoofing or deliberate anti-bot evasion.
- **Permission-first acquisition:** do not automate a consumer job board when its terms prohibit automated evaluation/extraction, even if a technically easy low-rate crawler exists.

## Stable property acquisition

Do not reopen absent a live regression:

- IMMMO #11: coverage OK, 13,948 seen, 1,167 pages, 9/9 shards, disappeared=0.
- s REAL #16: coverage OK, 314 seen, detail-enriched, disappeared=0.
- ImmoAds retired/disabled.

## Stable supplementary ATS job sources

### SmartRecruiters

Production #33 correctness/liveness/republish identity is closed:

- 15/15 shards, coverage OK, source_reported=411.
- 53 source-active listings / 42 relevant-active canonical jobs.
- 41/42 relevant locations resolved; Tirol regional scope intentionally non-point.
- stable republish identity uses tenant + `jobAdId`.

### Personio

Production #37 correctness/calibration is closed:

- DE + EN XML merged by stable position ID.
- 14/14 shards, 28 requests/pages, coverage OK.
- source_reported=215 without language doubling.
- 17 relevant-active canonical jobs.
- only unresolved relevant location is `österreichweit`, intentionally non-point.

Keep Personio as a supplementary feed. Do not manually add employers one by one as the primary scaling mechanism.

### Lever

Production #22 remains stable:

- 5/5 shards, coverage OK.
- 6 relevant active jobs.
- all relevant locations resolved.

A registry-driven verifier exists. Lever remains supplementary rather than the primary corpus strategy.

## Discovery gate v14 — correctness closed for now

Current version: `profile-seed-2026-08-28-v14`.

v14 fixes the FEM/`female` evidence-boundary bug while preserving real FEM/FEA/finite-element evidence. Existing generic support covers mechanical construction, HKLS/building-services, technical field service and production management while structurally excluding KFZ workshop trades.

Do not micro-calibrate discovery unless a broad corpus exposes a genuinely generic correctness bug. Candidate preference never belongs in discovery.

## Candidate profile / future fit

Candidate is fundamentally mechanical / Maschinenbau, not electrical.

Seed competence neighbourhood:

- mechanische Konstruktion / CAD;
- Bauteile, Baugruppen, Maschinenkomponenten;
- automotive, special vehicles, rail, chassis/suspension-like mechanical systems;
- product development;
- technical project work and supplier coordination;
- validation/testing and mechanically relevant assembly/commissioning.

Pure electrical engineering is explicitly outside competence and interest. Seed future candidate fit `electrical_engineering` as strong negative (`cannot + not want`) unless explicitly changed by the user. This affects candidate fit, not source acquisition.

## Consumer job boards: manual-only after terms review

The user correctly redirected acquisition toward the large job boards people actually search. Two low-impact prototypes proved that this produces far better mechanical vacancies with very few requests. However, a subsequent terms review found explicit automation prohibitions on the major boards examined.

**Do not automate these sources:**

- **karriere.at** — terms prohibit automated evaluation of the platform.
- **jobs.at** — Bewerber AGB prohibit automated evaluation of the platform.
- **AMS `alle jobs` / eJob-Room** — search data is for manual use; automated mechanisms are prohibited.
- **willhaben Jobs** — terms prohibit robot/crawler and automatic extraction mechanisms.
- **StepStone Austria** — terms prohibit scraping/comparable extraction techniques.
- **EURES public job search** — job-vacancy terms prohibit extraction for further processing and reserve API/data extraction to recognised EURES partner organisations.

These remain useful **manual discovery/reference sites for a human**, but they are not WohnWerk automated sources.

### Historical low-impact validation run #38: karriere.at

A prototype intentionally behaved like a human quick scan: five first pages, title gating, max eight details/query, sequential 0.65 s delay, no reconciliation.

Production #38 before the terms review:

- 5/5 shards, 0 failures;
- 35 HTTP requests total;
- 30 relevant jobs / 30 new;
- source-reported counts summed to 435;
- 34 relevant locations / 27 geo-resolved;
- 27 structured salaries / 14 annualized;
- no rate-limit/source errors.

The result proved the product idea but **must not remain an active automated source**. `scripts/run_karriere_at_jobs.py` now disables the source instead of crawling it.

### Historical low-impact validation run #39: jobs.at

Production #39 before the terms review:

- 5/5 shards, 0 failures;
- only 11 HTTP requests;
- 6 relevant jobs / 6 new;
- 8 relevant locations / 3 geo-resolved;
- 4 structured salaries;
- no source errors.

The result was technically clean but the jobs.at AGB also prohibit automated evaluation. `scripts/run_jobs_at_jobs.py` now disables the source instead of crawling it.

### Purging prototype board data

`scripts/purge_job_source_listings.py` exists to remove data obtained from a now-disallowed automated source.

- dry-run by default;
- reports source listings, affected canonical jobs and whether any canonical Job is shared with another source;
- `--apply` **refuses to modify the DB when `shared_jobs > 0`** so canonical-field contamination can be reviewed safely;
- with `shared_jobs=0`, it disables the source, removes its JobListings and deletes the now-orphan canonical Jobs.

Production needs a dry-run for both `karriere.at` and `jobs.at`, then apply only when each reports `shared_jobs=0`.

## PRIMARY automated job strategy — permission-first APIs and public feeds

The human-like search philosophy remains correct, but the transport changes:

1. prefer documented APIs/feeds explicitly intended for programmatic job retrieval;
2. keep request volume tiny (a handful of broad title searches, first page/frontier initially);
3. preserve source identity, location, salary and provenance;
4. never crawl advertiser pages merely to enrich an aggregator result unless explicitly permitted;
5. consumer boards with anti-automation terms remain manual-only;
6. ATS public feeds remain useful supplementary layers;
7. add more API/feed aggregators rather than manually enumerating employers.

### Adzuna Austria API — implemented, awaiting credentials/live probe

Adzuna is the first broad source found that fits the permission model:

- official documented REST API;
- API country enum explicitly supports `at`;
- API Terms explicitly allow personal research;
- default limits are 25 requests/min, 250/day, 1000/week, 2500/month;
- search results provide stable ad ID, title, truncated description, company, source location, redirect URL, salary fields, publication time and contract metadata;
- Adzuna requires the provided redirect URL for user navigation; WohnWerk stores that URL and does not crawl the advertiser behind it.

Files:

- `app/sources/job/adzuna.py`
- `scripts/run_adzuna_jobs.py`
- `tests/test_adzuna_job_source.py`

Current frontier:

- Austria endpoint only: `/jobs/at/search/1`;
- five title-only queries: Maschinenbau, Konstrukteur, CAD Konstrukteur, Entwicklungsingenieur, Technischer Projektleiter;
- up to 50 results/query, last 30 days, date-sorted;
- exactly one API request per query, no pagination yet;
- global minimum 2.5 s delay keeps the run under the documented 25 req/min default limit;
- cross-query stable-ID dedupe;
- always `coverage_complete=False`, never authoritative for disappearance;
- Adzuna description is explicitly marked source-truncated;
- salary predicted by Adzuna is tagged `ESTIMATED`, not employer-explicit;
- salary period is left unknown because the search response does not provide reliable period semantics;
- credentials are read only from `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`, never printed or persisted;
- errors are intentionally sanitized so query-string credentials cannot leak into logs.

A free Adzuna developer registration is required before the first production run.

### Other permission-first candidates

- **Jooble Austria** has an official REST API and currently advertises roughly 49k Austrian vacancies aggregated from ~1.3k sites. The Austrian API page requires an API-key application and the free API tier documentation states a 500-request lifetime quota. This is a strong second candidate after Adzuna.
- **Arbeitnow** exposes a free Europe job-board API with explicit API terms, but current Austria-specific density appears low; lower priority.
- EURES is not usable through its public vacancy API for this project because extraction/API access is restricted to recognised EURES partner organisations.

## Immediate work order

1. Finish CI for the Adzuna source + fail-closed purge utility.
2. On production, dry-run:
   - `python scripts/purge_job_source_listings.py karriere.at`
   - `python scripts/purge_job_source_listings.py jobs.at`
3. If each says `shared_jobs=0`, run the same commands with `--apply` and confirm both sources are disabled/removed from corpus.
4. Obtain Adzuna developer `app_id` + `app_key`; keep them only as environment/secrets on the WohnWerk host.
5. Run `python scripts/run_adzuna_jobs.py` once with defaults; no reconciliation.
6. Resolve locations and inspect source stats/rejection audit/source health.
7. If Adzuna Austria density is useful, keep it as the first broad API layer and add Jooble Austria next through its official API.
8. Continue ATS feeds in the background as supplementary sources.
9. At hundreds→thousands relevant jobs, implement normalized concepts, German profile review, candidate fit and house/job recommendations.
