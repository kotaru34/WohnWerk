# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-09-02 (Europe/Vienna)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `feature/germany`  
**Frozen AT release:** `release/v1-austria` at `89f1833f`  
**Draft PR:** #2 — `DE + AT country expansion`

This is the authoritative recovery point for a fresh context. Dynamic catalog counts are observations, not permanent invariants.

For the Germany product/UI/acquisition contract, read `docs/germany_mvp.md` immediately after this file. Do not infer the active task from the Austria version currently deployed in production.

## Release state

- Current production / frozen Austria release: **v0.3.47**.
- Production SHA: `89f1833f2b18ca35c2c0183ed60adcd327c0a2e4`.
- Production DB migration: `0011_live_ui_events` (head).
- Current Germany branch release candidate: **v0.4.0**.
- Germany branch DB migration: `0012_de_postal_codes` (head).
- Current concept extractor: `concept-seed-2026-09-01-v5`.
- Current discovery gate: `profile-seed-2026-08-30-v25`.
- Current salary policy: `explicit-salary-text-2026-08-30-v7`.
- Candidate fit policy: `candidate-fit-2026-08-28-v3`.
- Last code-bearing Germany HEAD before documentation refresh: `3c7dd3c519d34e98200d9959cf7d86b4996d6ac1`.
- Exact-head PR CI run #1121 on that code HEAD passed Install + Ruff + Compile + Tests: **556 passed, 2 warnings**.
- `docs/germany_mvp.md` was added at documentation commit `6cbfa0549058dc43a59a882eacdf352dee5f3308`; require CI on the final documentation HEAD before proceeding with target-server mutation.
- Exact-head GitHub CI is a hard deployment gate. Never deploy temporary development commits.

`/health` exposes application version and `job_concept_extractor`. Mutating refresh work fails closed when disk and running web release/extractor differ.

## Product invariants

WohnWerk is a private/self-hosted AT+DE property + job acquisition, personalization and matching system for the candidate/father. The Austria-only behavior frozen in `release/v1-austria` remains the compatibility baseline.

- Active development is the **Germany-oriented MVP** on `feature/germany` until this handoff says otherwise.
- Germany-specific product/UI/acquisition intent is authoritative in `docs/germany_mvp.md`.
- User UI is German-only.
- Häuser and Stellen catalogs are independent.
- Source lifecycle, discovery relevance and candidate fit are separate concerns.
- Failed/partial/degraded reconciliations never prove disappearance.
- Missing from bounded frontier scans is not disappearance proof.
- Disabled sources never contribute father-visible jobs.
- Hidden/favorite/viewed state survives lifecycle/canonical merges.
- Never invent coordinates, images, prices, salary semantics or property attributes.
- Geography/commute is separate from intrinsic candidate fit.
- No permanent Job×Property pair table unless measurements justify it.
- Only a complete authoritative `coverage=ok` reconciliation may prove disappearance.
- Country scope comes from `Source.config["country_code"]`; legacy sources default to AT.
- DE portal acquisition is public-only: no login, CAPTCHA solving, stealth or protection bypass.
- DE commercial property portal records retain minimal listing facts and source URLs, not descriptions, contacts or photos.

## Runtime

Public URL: `https://wohnwerk.kotaru.lainlounge.org`

- Caddy -> `127.0.0.1:8000`
- FastAPI/Uvicorn: `wohnwerk.service`
- local OSRM: `127.0.0.1:5000`
- refresh: `wohnwerk-refresh.timer`
- image worker: `wohnwerk-images.timer`
- liveness worker: `wohnwerk-liveness.timer`
- `/health` is unauthenticated
- father-facing routes use HTTP Basic
- never automate `/jobs/{id}` smoke because opening a job detail marks it viewed

Server timezone: `Europe/Vienna`.

Latest production sanity proof after the v0.3.47 Austria deploy:
- branch/release SHA observed: `89f1833f2b18ca35c2c0183ed60adcd327c0a2e4`
- services/timers reported active
- `/health`: `status=ok`, `service=wohnwerk`, `version=0.3.47`, extractor v5, `country=AT`, `ai_enabled=false`
- Alembic head remained `0011_live_ui_events`
- filesystem had healthy free space

## Candidate profile and matching

Profile slug: `mechanical-project-engineer`  
UI label: `Maschinenbau / technische Projektleitung`

Approx. 30 years mechanical engineering + technical project leadership. Strong neighborhood: senior mechanical engineering, development engineering, technical project/program leadership and engineering leadership. Structural/near exclusions include sales, software/IT development, pure electrical, construction/TGA/HKLS, technician/trade, junior/trainee, commercial PM, procurement and HR.

Manual father preferences include:
- `role:industrial-engineer = cannot_not_want`
- `role:quality-manager = cannot_not_want`

Concept extractor v5 adds the exact composite title alias `Mechanical/Fluids Engineer` to existing `role:mechanical-engineer`. Production proof: job #374 became score 69, coverage 1.000, compatible; v4->v5 changed exactly job #374 and all 248 relevant active jobs became scored.

## Job-source expansion phase: CLOSED

Do not continue generic job-source expansion. Existing enabled job sources are maintained/fixed only unless a concrete coverage gap justifies reopening.

PALFINGER promotion is complete; do not rerun PALFINGER reconciliation merely to re-prove it.

Germany-specific job sources already present in `feature/germany` are part of the Germany MVP bootstrap, not a signal to reopen unconstrained source expansion:
- Bundesagentur Jobsuche / Arbeitsagentur public source
- Adzuna DE when credentials are configured

## Salary state

Policy: `explicit-salary-text-2026-08-30-v7`.

Important invariants:
- preserve source period
- no automatic Austrian monthly ×14
- monthly annualization only with explicit payment count
- hourly remains non-annualized without defensible hours/year
- structured source salary wins text
- no invented period semantics

v0.3.39 repaired detail salary acquisition and Greenhouse structured pay ingestion. Production backfill proved:
- StepStone job 363: EUR 3700/month, no invented annualization
- Willhaben job 365: EUR 19.98/hour
- GROPYUS job 384: EUR 55k..60k/year structured
- Willhaben job 385: EUR 17.50/hour

## Property sources and semantics

Authoritative Austria property sources:
- `immmo.at`
- `sreal.at`

Germany branch sources pending target-server smoke/reconciliation proof:
- `immoscout24-de`: public HTML/context, 16 states x 3 price bands, newest-first incrementals.
- `immowelt-de`: ordinary Chromium-rendered public search, the same 48 shards, hard fail at page 250 or any challenge.

Neither DE source has disappearance authority merely because code exists. Authority begins only
after a real complete run reports all shards successful, uncapped and count-plausible. Any failed,
partial, capped or parser-incomplete run remains non-authoritative.

For these German commercial property portals, the retained dataset is deliberately minimal: source identity/URL, title, price, explicit living/plot area where exposed, PLZ/city and internal provenance/lifecycle metadata. Do not retain portal descriptions, seller/broker contacts or portal-hosted photos. See `docs/germany_mvp.md`.

ImmoAds remains disabled.

Property rules:
- explicit Wohnfläche/Wohnnutzfläche -> living area
- explicit Grundstück/Grundstücksfläche/Grundfläche -> plot area
- explicit Nutzfläche -> usable area
- generic source area -> neutral display-only area
- source-backed images only where the source/access model allows image use; German commercial portal adapters above intentionally do not retain photos
- conservative dedupe only
- never invent property coordinates or attributes

## House radius

v0.3.39 repaired the active `/houses` route after the v0.3.38 radius regression. Production proof: `/houses` 200 and Salzburg exact 1 -> Salzburg 50 km 37. Saved `radius_km` is 1..250 km, uses stored Austrian postal/locality centroids and PostGIS `ST_DWithin`; unresolved centers fail closed.

Germany requires the new five-digit postal-code path introduced by migration `0012_de_postal_codes` and the GeoNames DE postal centroid import. Do not route German rows through Austria-only PLZ assumptions.

## Job geography

v0.3.41 repaired 11 concrete unresolved location rows without inventing points. v0.3.46 closed the remaining evidence-backed concrete geo cleanup.

### v0.3.46 production proof

Atomic production SHA: `00c3c6eb920efc481b5ce2c2fd12a5f1bb25c4f3`. Exact-head CI and production server gate both passed with **544 tests**.

The production repair was deliberately targeted and created no crawl run:
- `crawl_runs`: 719 -> 719
- `job_locations`: 484 -> 483, exactly the redundant country-code row removal
- job #138 / SPIEGLTEC: `Schaftenau` resolved through verified postal membership `6336` and the local BEV-backed postal centroid to `POINT(12.09684228 47.5425033)`
- job #352 / teampool: `Puntigam` resolved through verified postal membership `8055` to `POINT(15.43172668 47.02476775)`
- method for both: `verified_sublocality_postal_centroid`
- job #160 / Lam Research: redundant non-remote `AT, Österreich` row removed; the correct Salzburg row remains resolved at `POINT(13.04387009 47.8015246)`
- no DB migration; Alembic remains `0011_live_ui_events`
- `/houses`, `/jobs`, Salzburg+50km and external `/health` passed
- refresh/images/liveness timers were restored active

Remaining active null-point labels after the repair are broad scopes, not missing concrete geocodes:
- `Wels-Land`
- `Bezirk Wels-Land`
- `Graz Umgebung-West`
- `Kärnten`
- `österreichweit`

Never invent one point for these scopes.

### v0.3.47 ops geo semantics

A production screenshot after v0.3.46 exposed an operational presentation bug: `/admin/health` still titled every active non-remote null-point `JobLocation` as `Noch nicht aufgelöste konkrete Ortsangaben`, so the broad scopes above looked like unresolved resolver failures.

v0.3.47 fixes the semantic boundary rather than merely renaming the UI:
- `app.jobs.location_resolution.is_non_point_location_scope()` is the shared classifier used by both the resolver and Ops UI
- Bundesland/country/explicit district labels remain non-point
- explicit operational broad scopes include `österreichweit`, `Wels-Land`, and `Graz Umgebung-West`
- `Bezirk ...` is classified as a district scope
- `Salzburg Umgebung` is deliberately **not** classified as a permanent non-point scope because its explicit Salzburg anchor remains resolvable through `area_anchor_locality`
- `canonicalize_locality()` now returns `None` for the explicit broad scopes for a documented semantic reason, rather than only failing later because no postal row happens to match
- `collect_ops_snapshot()` performs one grouped query and splits null-point labels into concrete resolver backlog vs intentional non-point scopes
- `snapshot.unresolved_job_locations` and `snapshot.unresolved_labels` now mean **concrete unresolved** only
- new `snapshot.non_point_job_locations` and `snapshot.non_point_labels` expose the informational broad-scope population separately
- `/admin/health` top counter is labeled `konkrete ungeocodierte Job-Orte`
- broad scopes render under `Regionale / landesweite Ortsangaben` with an explanation that they are intentionally not artificially geocoded
- no JobLocation data mutation and no DB migration are required

Regression tests cover the five production labels, preserve `Salzburg Umgebung` behavior, verify the Ops split, and verify both sections of the German admin UI.

Development CI initially exposed two stale v0.3.46 tests that asserted the literal application version `0.3.46`. Those tests were removed rather than mechanically bumped because version-pinning is not a behavioral invariant; all actual v0.3.46 geo regression coverage remains. Final development CI was green with Ruff/Compile clean and **544 tests passed** before the Germany branch expansion added further tests.

Production was subsequently advanced to the frozen Austria v0.3.47 release at `89f1833f` and sanity-checked successfully as recorded above.

## IMMMO coverage authority

v0.3.42 remains the active IMMMO coverage policy. It separates structural source coverage from stable synthetic/source-less identity share.

Policy `immmo-identity-churn-2026-09-01-v1`:
- structural authority requires reconciliation + traversal complete + no cap + cards_seen==cards_parsed + count delta in tolerance
- after ingest, each shard counts genuinely new synthetic identities
- identity churn fails closed if new synthetic rows exceed `max(3, 1% of cards seen)`
- legacy total-synthetic link-quality remains diagnostic only
- stable source-less cards can therefore remain authoritative
- a parser regression that creates many new synthetic identities still degrades coverage

Do not manually change `Source.coverage_status`. Only a real complete reconciliation controls disappearance authority.

## Source health semantics

Execution success and coverage authority are independent:
- complete successful authoritative scan -> `success / ok`
- successful bounded incremental -> successful execution, non-authoritative coverage
- mixed actual failures -> `partial / degraded`
- all failed -> `failed / failed`

Only `coverage=ok` reconciliation may prove disappearance.

## SSE/live synchronization

v0.3.43 introduced durable SSE invalidation events; v0.3.44 fixed isolated-process SQLAlchemy model registration for durable event writes.

Production-proven architecture:
- durable `live_ui_events` journal in Postgres, migration `0011_live_ui_events`
- authenticated `GET /events`
- monotonic event IDs and reconnect replay
- separate crawler/web processes work through Postgres, not an in-memory broker
- curation events are atomic with authoritative writes
- job catalog invalidation is emitted only after location resolution/propagation and concept normalization all succeed

v0.3.44 production proof included successful durable event insert and authenticated replay through Caddy/TLS.

## v0.3.45 in-place curation UX

v0.3.45 is production-proven manually. The original SSE release still allowed legacy browser `POST -> 303` navigation when clicking `Ausblenden`/`Favorit`, causing scroll jumps. v0.3.45 fixes that interaction layer while preserving backend POST+CSRF authority.

Current behavior:
- catalog house/job favorite/hidden forms are delegated through `fetch()` + `FormData`
- `preventDefault()` prevents browser navigation
- buttons are disabled while the POST is in flight
- successful updates refresh the current server-rendered `<main>` in place
- viewport anchor + `scrollY` are captured/restored around replacement
- if the just-hidden card disappears, prior scroll offset is retained instead of jumping to top
- SSE-triggered refresh uses the same viewport-preserving mechanism
- without JS, legacy POST+303 remains a fallback
- hiding the currently open `/houses/{id}` detail page deliberately keeps navigation semantics because the hidden detail URL is no longer valid

Manual production verification: `Ausblenden` works without reload/navigation and without the page jumping upward.

## Germany MVP implementation checkpoint

Current code in `feature/germany` already contains:
- DE/AT country scoping for `/houses`, `/jobs`, `/matches` using `Source.config["country_code"]` and a compact persistent UI switch;
- migration `0012_de_postal_codes` and German postal-code import support;
- `immoscout24-de` fail-closed public-search adapter with 48 deterministic shards;
- `immowelt-de` fail-closed ordinary-Chromium public-search adapter with the same 48 shards;
- German job-source code for Arbeitsagentur/Bundesagentur and Adzuna DE;
- country-aware OpenImmo support for explicitly authorized feeds;
- regression coverage protecting Austria semantics while adding Germany behavior.

The last code-bearing HEAD `3c7dd3c...` passed exact-head PR CI with **556 passed, 2 warnings**. Documentation commits after it do not change runtime behavior but must still pass the branch CI gate before target-server mutation.

## Current near-term roadmap

1. **DONE for code HEAD `3c7dd3c...`:** exact-head GitHub CI passed Install + Ruff + Compile + Tests with 556 tests.
2. **CURRENT:** require green exact-head CI on the final documentation HEAD, then begin target-server Germany bootstrap.
3. Apply migration `0012_de_postal_codes` on the target DB and verify Alembic head.
4. Import GeoNames DE postal centroids and sanity-check count plus representative five-digit PLZ rows.
5. Install the matching Playwright Chromium runtime before enabling `immowelt-de`.
6. Run one manual incremental smoke for `immoscout24-de`; inspect shard failures, cap hits, source/parsed counts and representative PLZ/price/living-area/plot-area records.
7. Run one manual incremental smoke for `immowelt-de` with the same inspection; any challenge/access protection must fail closed.
8. Run the first `--reconcile` for a DE property source only after its incremental smoke is healthy. Do not manually promote coverage or deactivate listings if the run is partial/degraded.
9. Bootstrap Germany jobs after the property acquisition path is proven: Bundesagentur needs no user account; configure Adzuna credentials only if that source is desired.
10. Add a German OpenImmo feed only when its owner provides or authorizes the feed URL.

## Deployment discipline

For every branch change:
1. inspect final diff
2. wait for GitHub CI on exact branch HEAD
3. require Install + Ruff + Compile + Tests success
4. squash development commits into one atomic release commit over current production when preparing a production release
5. wait for exact-head CI on that atomic release SHA
6. only then deploy
7. production reruns Ruff/compile/tests before restart
8. verify `/health` plus targeted production controls
9. never deploy a red/intermediate SHA
