# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-10-03  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active development branch:** none — v0.4.12 is deployed and production-accepted  
**Production release:** `release/v0.4.12`; deployed code SHA `96656cd96091b33944824e5cb1b003142e7012d8`  
**Active PR:** post-deploy acceptance/HANDOFF branch `ops/v0.4.12-acceptance`  
**Frozen Austria baseline:** `release/v1-austria` at `89f1833f`

This file is the authoritative recovery point for a fresh context. Read
`docs/germany_mvp.md` immediately after it, then `docs/requirements.md`,
`docs/acquisition.md` and `docs/sources.md`.

Host-level machine recovery companion (intentionally **not** stored in Git):
`/home/sentinel-ai/WohnWerk_MACHINE_HANDOFF.md`. For infrastructure/deployment work,
read that file through Tethys Sentinel before rediscovering host layout, services or tooling.
Update it only when ChatGPT itself installs software or materially changes the host/runtime.

Dynamic database/catalog counts are observations, not permanent invariants.

## Current product decision

The active Germany phase is now **house-only**.

- Germany property acquisition/evaluation remains active.
- Germany job acquisition, source expansion and debugging are fully paused until the operator explicitly reopens them.
- Existing Austrian job acquisition/profile/ranking remains the compatibility baseline.
- Workplace distance for German houses is based on an explicitly configured workplace location, not on a German job listing.
- Current Germany house purchase target is **EUR 30,000..200,000**.
- The external Immowelt challenge handler is operator-owned code. WohnWerk automation must not edit, refactor, install dependencies into, or otherwise modify that handler implementation unless the operator explicitly changes this rule.
- WohnWerk owns everything around that handler boundary: detection, persistence, handoff contract, timeout/error behavior, same-run resume, source isolation, telemetry, tests and deployment.

## Release/runtime state

Production is deployed and accepted on **v0.4.12**.

- deployed application version: **v0.4.12**
- exact deployed Git SHA: `96656cd96091b33944824e5cb1b003142e7012d8`
- exact release branch: `release/v0.4.12`
- rollback ref `refs/wohnwerk/rollback-v0.4.11-pre-v0.4.12` points to v0.4.11 SHA `6d7fd14cefbff75bed3957a5443c419c04db8501`
- database migration head remains `0017_internet_source_evidence`; v0.4.12 has no DB migration
- v0.4.12 has no dependency changes
- exact-release GitHub CI workflow `37086602828`: Install, Ruff, Compile and Tests passed, **689 passed, 2 warnings**
- production target-host/live gate and deployment completed through Sentinel relay issue #76
- final `/health` reports `version=0.4.12`
- final live checkout HEAD is exactly `96656cd96091b33944824e5cb1b003142e7012d8` and the production worktree is clean
- `wohnwerk.service`, `wohnwerk-refresh.timer`, `wohnwerk-images.timer` and `wohnwerk-liveness.timer` are all active
- `iad-de` is the new operational Germany broker-network source: target-host page 1 exposed 9/9 parseable cards with source-reported corpus 932 and no reconciliation authority
- production iad bootstrap Run #5175 completed successfully over 8 pages: **9 seen, 9 new, 0 updated**, source-reported corpus 932; coverage is deliberately `degraded` / frontier-only and disappearance authority remains `never`
- `remax-de` is retained only as a diagnostic adapter: target-host access returned Cloudflare Turnstile `Security Verification`; the adapter detects it and halts fail-closed, it is absent from the automatic scheduler, and no challenge bypass is attempted
- branded source metadata and bounded source-backed heating support include iad; RE/MAX branding may remain for historical/diagnostic provenance but blocked RE/MAX is not part of production acquisition coverage
- the recurring non-fatal PostgreSQL timezone warning remains: timezone alias `Europe/Kiev` is treated as UTC by the client
- `von-poll-de` remains disabled fail-closed after HTTP 403
- `immoscout24-de` remains unscheduled behind the explicit challenge boundary
- `immowelt-de` remains the broad Germany portal source
- `immonet.de` remains intentionally absent as a distinct source because it aliases/redirects into Immowelt

v0.4.12 shipped:
- a dedicated `iad-de` bounded public house frontier with stable source IDs from detail slugs, PLZ/city, asking price, explicit living/plot area where present and source-backed preview provenance;
- iad scheduler integration as failure-isolated, incremental/frontier-only acquisition with no disappearance authority;
- iad branded provenance and bounded heating-detail enrichment integration;
- a RE/MAX Germany adapter plus tests/diagnostics, but production scheduling is intentionally disabled after the target-host Turnstile gate;
- explicit RE/MAX challenge detection so a HTTP-200 verification page cannot be misclassified as an empty/valid listing page;
- a repo-owned read-only live source probe used before cutover to prove the exact candidate against the production host;
- all v0.4.11 source-badge, s REAL repair, dedupe, Germany suitability and Austria compatibility behavior preserved.

### v0.4.12 production proof

Trusted release proof is the exact-head GitHub CI plus HMAC-verified Sentinel issue #76:

- exact release SHA: `96656cd96091b33944824e5cb1b003142e7012d8`, exactly one commit over deployed v0.4.11;
- CI #37086602828: **689 passed, 2 warnings** with Ruff and compile green;
- pre-cutover v0.4.11 HEAD/worktree/health/four-unit invariants passed;
- read-only target-host gate: RE/MAX challenge detected and fail-closed; iad 9/9 live cards parsed, `source_reported=932`, `coverage_complete=False`;
- rollback ref created before cutover;
- production checkout moved to the exact release SHA and `wohnwerk.service` restarted successfully;
- post-restart health reported `0.4.12`;
- iad production bootstrap Run #5175 succeeded with 9 new listings from the bounded eight-page scan;
- final production HEAD is exact, Git worktree clean, all four core units active, and final health still reports `0.4.12`.

v0.4.11 shipped:
- branded provenance badges on house catalog cards and house detail, with all unique retained sources on deduplicated canonical properties;
- centralized source-brand metadata, including s REAL, IMMMO, Immowelt, Kleinanzeigen, Engel & Völkers, ImmoScout24, VON POLL and willhaben;
- s REAL search-card and detail-page location parsing hardened so a title year cannot be promoted to a postcode or swallowed into the city;
- targeted dry-run-by-default persisted-location repair tooling;
- the affected production Loidesthal property repaired and live-accepted;
- v0.4.10's conservative dedupe, source-backed heating, DE previews and shared grouped house-fact UI preserved.

### v0.4.11 production proof

Trusted post-deploy proof is the HMAC-verified Sentinel output from issues #74/#75 plus exact-release CI:

- exact deployed SHA: `6d7fd14cefbff75bed3957a5443c419c04db8501`;
- final Git tree: clean;
- health: `status=ok`, `version=0.4.11`;
- all four WohnWerk service/timer units: active;
- property `62724`: `2225 Loidesthal`;
- listing repair evidence: all postal/city fields agree with `2225 Loidesthal`;
- production catalog: HTTP 200, s REAL badge before seen status, repaired location and fact groups verified;
- production detail: HTTP 200, s REAL badge before seen status, repaired location and fact groups verified;
- property media: HTTP 200, `image/jpeg`;
- acceptance verifier commit `890a7647924dc30b4a2e4ad1d10ce43c67fbfaac` passed GitHub CI workflow `37081977187` (Install, Ruff, Compile, full Tests) before being executed from temporary storage against deployed production code/settings/DB.

The v0.4.1 step:
- removes `adzuna-api-de` and `arbeitsagentur-jobsuche-de` from automatic refresh plans;
- adds regression coverage that DE job sources are not scheduled;
- records the house-only Germany scope and new house requirements;
- versions the external handler request contract as v1;
- assigns stable IDs to newly created challenge handoffs while keeping old persisted runs compatible;
- launches the external handler with a minimal allowlisted environment instead of inheriting the complete WohnWerk runtime environment;
- documents the boundary in `docs/immowelt_handler_contract.md`;
- does not modify the external challenge-handler implementation.

The deployed v0.4.1 PR #5 code HEAD is
`0890f0283e217b84a9de37e418a6fb6677391c66`, GitHub Actions CI #1231:
Install + Ruff + Compile + Tests, **592 passed, 2 warnings**.

Production-host gates were also run against that exact SHA before the live checkout changed:
- Ruff: passed;
- Python compile: passed;
- full pytest: **592 passed, 2 warnings**.

Post-deploy proof:
- local `/health`: `status=ok`, `version=0.4.1`, `country=AT`;
- live checkout SHA exactly `0890f0283e217b84a9de37e418a6fb6677391c66`;
- live Git tree clean;
- `wohnwerk.service`, `wohnwerk-refresh.timer`, `wohnwerk-images.timer`, `wohnwerk-liveness.timer`: all active;
- deployed regression `test_de_job_sources_are_not_scheduled`: passed;
- Austria acquisition plans `immmo.at` and `sreal.at` remain registered;
- no migration or dependency-file change was part of this release;
- temporary candidate worktree and test venv were removed after verification;
- temporary `sentinel-ai` passwordless sudo delegation was removed;
- the external Immowelt challenge-handler implementation was not modified and Run #990 was not resumed.

### v0.4.2 production proof

The deployed v0.4.2 code SHA is
`88d578ca191071eba6bc2ab0ccbe466f9f966b3a`.

GitHub Actions CI #1240 passed on that exact candidate:
- Install: passed;
- Ruff: passed;
- Compile: passed;
- Tests: **599 passed, 2 warnings**.

Production-host gates were then run against the same exact SHA in an isolated temporary worktree/venv:
- Ruff: passed;
- Python compile: passed;
- full pytest: **599 passed, 2 warnings**.

Deployment proof:
- local `/health`: `status=ok`, `version=0.4.2`, `country=AT`;
- live checkout SHA exactly `88d578ca191071eba6bc2ab0ccbe466f9f966b3a`;
- live Git tree clean;
- `wohnwerk.service`, `wohnwerk-refresh.timer`, `wohnwerk-images.timer`, `wohnwerk-liveness.timer`: all active after cleanup;
- rollback ref `refs/wohnwerk/rollback-v0.4.1-pre-v0.4.2` points to v0.4.1 SHA `0890f0283e217b84a9de37e418a6fb6677391c66`;
- no database migration or dependency-file change was required;
- temporary v0.4.2 candidate worktree and test venv were removed;
- temporary `sentinel-ai` passwordless sudo delegation was removed as the final privileged deployment action;
- the external Immowelt challenge handler was not modified or invoked;
- Run #990 was not resumed.

### v0.4.3 production proof

The deployed v0.4.3 release SHA is
`f9d7e994c6264053c77d9e06c0f4eb586e92ea8f`.

GitHub Actions CI #1246 passed on that exact atomic release commit:
- Install: passed;
- Ruff: passed;
- Compile: passed;
- Tests: **609 passed, 2 warnings**.

Production deployment proof:
- pre-deploy production SHA was exactly `88d578ca191071eba6bc2ab0ccbe466f9f966b3a` and the tree was clean;
- rollback ref `refs/wohnwerk/rollback-v0.4.2-pre-v0.4.3` points to that v0.4.2 SHA;
- production-host Ruff and Python compile gates passed on an isolated exact-release worktree;
- pre-migration DB revision was `0012_de_postal_codes`;
- migration `0012_de_postal_codes -> 0013_candidate_house_policy` completed successfully under PostgreSQL transactional DDL;
- post-migration DB revision is `0013_candidate_house_policy (head)`;
- local `/health`: `status=ok`, `version=0.4.3`, `country=AT`;
- live checkout SHA exactly `f9d7e994c6264053c77d9e06c0f4eb586e92ea8f`;
- live Git tree clean;
- `wohnwerk.service`, `wohnwerk-refresh.timer`, `wohnwerk-images.timer`, `wohnwerk-liveness.timer`: all active after cleanup;
- temporary v0.4.3 candidate worktree and validation venv were removed;
- temporary `sentinel-ai` passwordless sudo delegation was removed as the final privileged deployment action;
- the external Immowelt challenge handler was not modified or invoked;
- Run #990 was not resumed.

A production-host full pytest execution reported **609 passed, 2 warnings**, but that historical relay response did not pass later local MAC re-verification, so it is intentionally not treated as trusted deployment proof. The exact atomic release CI #1246 is the trusted full-suite proof.

### v0.4.4 production proof

The deployed v0.4.4 release SHA is
`4472cb160f7f599e5c956d22b03bbcf299c4e556`.

GitHub Actions CI #1265 passed on that exact atomic release commit:
- Install: passed;
- Ruff: passed;
- Compile: passed;
- Tests: **616 passed, 2 warnings**.

Production deployment proof:
- pre-deploy production SHA was exactly `f9d7e994c6264053c77d9e06c0f4eb586e92ea8f` and the tree was clean;
- rollback ref `refs/wohnwerk/rollback-v0.4.3-pre-v0.4.4` points to that v0.4.3 SHA;
- production-host Ruff and Python compile gates passed on an isolated exact-release worktree;
- a production-host full pytest rerun completed successfully with HMAC-verified relay proof; the exact test count is taken from CI #1265 rather than inferred from the quiet host rerun;
- the earlier verbose production-host pytest response reported 616 passed but failed later HMAC re-verification and is intentionally not trusted;
- pre-migration DB revision was `0013_candidate_house_policy (head)`;
- migration `0013_candidate_house_policy -> 0014_candidate_workplace` completed successfully under PostgreSQL transactional DDL;
- post-migration DB revision is `0014_candidate_workplace (head)`;
- local `/health`: `status=ok`, `version=0.4.4`, `country=AT`;
- live checkout SHA exactly `4472cb160f7f599e5c956d22b03bbcf299c4e556`;
- live Git tree clean;
- `wohnwerk.service`, `wohnwerk-refresh.timer`, `wohnwerk-images.timer`, `wohnwerk-liveness.timer`: all active after deployment;
- an actual workplace value was not required or fabricated for deployment smoke;
- temporary v0.4.4 validation worktree and venv were removed;
- temporary `sentinel-ai` passwordless sudo delegation was removed as the final privileged action;
- the external Immowelt challenge handler was not modified or invoked;
- Run #990 was not resumed.

### v0.4.5 production proof

The deployed v0.4.5 release SHA is
`e1b42a425e469a291298196f25b54a328341da86`.

GitHub Actions exact-head CI #1271 passed on that exact atomic release commit:
- Install: passed;
- Ruff: passed;
- Compile: passed;
- Tests: **625 passed, 2 warnings**.

Production deployment proof:
- pre-deploy production SHA was exactly `4472cb160f7f599e5c956d22b03bbcf299c4e556` and the tree was clean;
- rollback ref `refs/wohnwerk/rollback-v0.4.4-pre-v0.4.5` points to that v0.4.4 SHA;
- pre-migration DB revision was `0014_candidate_workplace (head)`;
- an isolated exact-release production-host worktree/venv passed Ruff, Python compileall and full pytest before cutover;
- migration `0014_candidate_workplace -> 0015_hospital_access` completed successfully under PostgreSQL transactional DDL;
- the pinned official Bundes-Klinik-Atlas Open Data export dated **2026-09-01** was ZIP-integrity-tested before cutover and imported only after the migration;
- the import completed successfully with **1,572 hospital facilities**;
- post-import readback recorded `coverage_status=ok`, `dataset_date=2026-09-01`, `facility_count=1572`;
- post-migration DB revision is `0015_hospital_access (head)`;
- local `/health`: `status=ok`, `version=0.4.5`, `country=AT`;
- live checkout SHA exactly `e1b42a425e469a291298196f25b54a328341da86`;
- live Git tree clean;
- `wohnwerk.service`, `wohnwerk-refresh.timer`, `wohnwerk-images.timer`, `wohnwerk-liveness.timer`: all active after cleanup;
- a final post-cleanup health check still reported v0.4.5 and all four units remained active;
- temporary v0.4.5 validation worktree, venv and Atlas ZIP were removed;
- temporary `sentinel-ai` passwordless sudo delegation was removed as the final privileged deployment action;
- the external Immowelt challenge handler was not modified or invoked;
- Run #990 was not resumed.

### v0.4.6 production proof

The deployed v0.4.6 release SHA is
`7e636b6edd80a1db0e56c160fc383c5630121008`.

GitHub Actions exact-release CI #36336089862 passed on that exact atomic release commit:
- Install: passed;
- Ruff: passed;
- Compile: passed;
- Tests: **629 passed, 2 warnings**.

Production deployment proof:
- pre-deploy production SHA was exactly `e1b42a425e469a291298196f25b54a328341da86` and the tree was clean;
- rollback ref `refs/wohnwerk/rollback-v0.4.5-pre-v0.4.6` points to that v0.4.5 SHA;
- an isolated exact-release production-host validation venv passed Ruff, compileall and full pytest: **629 passed, 2 warnings**;
- pre-migration DB revision was `0015_hospital_access`;
- migration `0015_hospital_access -> 0016_internet_access` completed successfully under PostgreSQL transactional DDL;
- the official Bundesnetzagentur Breitbandatlas / Gigabit-Grundbuch snapshot dated **2025-12-31** was ZIP-integrity-tested and GeoPackage-validated before import;
- source GeoPackage row count: **3,590,703** 100×100 m grid cells;
- post-import readback recorded `coverage_status=ok`, `dataset_date=2025-12-31`, `source_row_count=3590703`;
- property Internet evidence rows remain **0 by design** because current DE property coordinates are PLZ centroids and are not defensible for 100 m house-level matching;
- post-migration DB revision is `0016_internet_access (head)`;
- local `/health`: `status=ok`, `version=0.4.6`;
- live checkout SHA exactly `7e636b6edd80a1db0e56c160fc383c5630121008`;
- live Git tree clean;
- `wohnwerk.service`, `wohnwerk-refresh.timer`, `wohnwerk-images.timer`, `wohnwerk-liveness.timer` and Caddy all active after cleanup;
- temporary validation/staging artifacts were removed;
- persistent host notes were updated in `/home/sentinel-ai/WohnWerk_MACHINE_HANDOFF.md`;
- temporary `sentinel-ai` passwordless sudo delegation was removed as the final privileged deployment action.

### v0.4.7 production proof

The deployed v0.4.7 release SHA is
`a1423e7aee4c59c61508f54e74f1cdfc20a9948b`.

GitHub Actions exact-release CI #36341041240 passed on that exact atomic release commit:
- Install: passed;
- Ruff: passed;
- Compile: passed;
- Tests: **632 passed, 2 warnings**.

Production deployment proof:
- pre-deploy production SHA was exactly `7e636b6edd80a1db0e56c160fc383c5630121008` and the tree was clean;
- rollback ref `refs/wohnwerk/rollback-v0.4.6-pre-v0.4.7` points to that v0.4.6 SHA;
- an isolated exact-release production-host validation environment passed Ruff, compileall and full pytest: **632 passed, 2 warnings**;
- v0.4.7 has no database migration and does not modify the imported broadband dataset;
- local `/health` reported `status=ok`, `version=0.4.7`;
- live checkout SHA is exactly `a1423e7aee4c59c61508f54e74f1cdfc20a9948b`, detached and clean;
- `wohnwerk.service`, `wohnwerk-refresh.timer`, `wohnwerk-images.timer`, `wohnwerk-liveness.timer` and Caddy are all active;
- the four previous inline house controls are consolidated into one settings dialog with one combined save action;
- DE-specific PLZ/hospital/Internet policy writes remain DE-only; Austria policy semantics were not changed by the UI release;
- v0.4.7 validation staging was removed;
- persistent host notes were updated in `/home/sentinel-ai/WohnWerk_MACHINE_HANDOFF.md`;
- temporary `sentinel-ai` passwordless sudo delegation was removed as the final privileged action;
- final read-only verification after bootstrap removal confirmed that the bootstrap path and all v0.4.7 validation paths are absent, `/health` still reports v0.4.7, all five units remain active, and the production Git tree remains clean on the exact release SHA.

The last directly verified DB/data authority state remains the v0.4.6 state because v0.4.7 contains no DB/data changes:
- DB head `0016_internet_access`;
- DE Breitbandatlas / Gigabit-Grundbuch snapshot `2025-12-31`;
- `coverage_status=ok`;
- `source_row_count=3590703`;
- property Internet evidence rows remain 0 while current DE property coordinates are PLZ centroids.

Internet-data authority semantics in production:
- source evidence is DE-only in this release; Austria broadband behavior was not changed;
- Broadbandatlas percentages describe household coverage in a 100×100 m cell, not exact-address service;
- NULL coverage is not treated as 0;
- a PLZ centroid never qualifies for property-to-grid matching;
- Internet price/provider remain unknown unless a separate source backs them;
- Starlink remains an explicit fallback concept and is not mixed into terrestrial coverage evidence.

Hospital-data authority semantics in production:
- Bundes-Klinik-Atlas is the DE hospital source for this release;
- Standort identity, coordinates, Notfallstufe and capability modules are source-backed;
- a current emergency level is only treated as confirmed when `Stufe` is 1..3 and `StufeNichtVereinbart` is not true;
- capability modules such as Schwerverletztenversorgung, Kinder-Notfallstufe, Spezialversorgung, Stroke Unit and Chest Pain Unit are retained separately rather than inferred from a hospital name;
- hospital-distance rejection is local suitability logic and does not mutate source lifecycle/provenance;
- missing hospital evidence remains fail-open by default, with explicit fail-closed behavior configurable by the operator;
- partial/failed hospital imports do not gain authority because suitability only trusts dataset state with `coverage_status=ok`.

The active development branch may move beyond the deployed SHA with documentation-only handoff commits. Production remains pinned to the deployed code SHA above until a later explicitly gated deployment.

## Production access/deployment discipline

For every production-affecting branch change:

1. inspect the final diff;
2. require GitHub CI on the exact branch HEAD;
3. require Install + Ruff + Compile + Tests success;
4. when preparing a production release, squash development work into one atomic release commit over the current production baseline where practical;
5. require exact-head CI on that release SHA;
6. only then mutate production;
7. production reruns the relevant lint/compile/tests before restart;
8. verify `/health` and targeted functional controls after restart;
9. never deploy a red/intermediate SHA;
10. do not use `/jobs/{id}` as an automated smoke because opening a job detail marks it viewed.

Every newly released feature version bumps the WohnWerk version. Update this handoff when:
- a new project version is released/deployed;
- a large implementation step completes even without a release;
- extended discussion changes the agreed next step or product contract.

## Core data truth/lifecycle invariants

- Never invent coordinates.
- Never invent prices, salary semantics, areas, heating type, hospital capability or Internet availability.
- Explicit Wohnfläche/Wohnnutzfläche maps to living area.
- Explicit Grundstück/Grundstücksfläche/Grundfläche maps to plot area.
- Ambiguous/generic area remains ambiguous/display-only.
- Preserve source provenance.
- Deduplicate conservatively; source listings survive underneath a canonical house.
- User hidden/favorite/viewed state must survive lifecycle/canonical merges.
- Incremental scans discover; they never prove disappearance.
- Failed/partial/degraded/paused/skipped/challenged/capped/parser-incomplete scans never prove disappearance.
- Only a complete authoritative `coverage=ok` reconciliation may mark unseen listings inactive.
- Do not manually promote `Source.coverage_status`.
- One source failing must not stop unrelated acquisition.
- Austria behavior remains the compatibility baseline unless an explicit later decision changes it.

## Germany postal/geography

Germany uses five-digit postal codes through migration `0012_de_postal_codes`.

GeoNames supplies approximate DE postal centroids. Austria locality resolution remains source/country scoped so DE rows cannot contaminate Austria assumptions.

German rows must never be routed through Austria-only four-digit PLZ logic.

## Germany jobs — PAUSED

Operator decision on 2026-09-26:

- Germany jobs are not needed for the current project phase.
- `adzuna-api-de` and `arbeitsagentur-jobsuche-de` adapters/scripts may remain dormant in the repository.
- They are intentionally absent from the automatic refresh scheduler in v0.4.1.
- Do not spend work on German job crawling, credentials, ranking, geocoding, reconciliation or source expansion.
- Austrian job sources/profile/ranking stay operational and unchanged.
- A future operator decision is required to reopen Germany jobs.

## ImmoScout24 DE

ImmoScout24 is paused on the current server environment.

Observed behavior from the Germany bootstrap:
- plain HTTP returned a challenge/401 path;
- stock headless and headed Chromium also hit the human challenge;
- no challenge solver, copied clearance state, stealth framework, proxy rotation or deliberate access-control bypass is added to WohnWerk.

Its adapter may remain for a future environment, but it is not in the automatic scheduler.

## Immowelt DE

Immowelt is the active broad Germany property source.

Production transport:
- public `/classified-search` frontend;
- stock Playwright/Chromium;
- headed under the dedicated Xvfb display;
- no login;
- no stealth/fingerprint masking framework in WohnWerk;
- normal discovery does not open listing details;
- heavy image/media/font resources may be suppressed;
- source failures are isolated from the global refresh service;
- automatic mode remains incremental/frontier only while coverage behavior is being validated.

### Resumable challenge boundary

WohnWerk owns a resumable state machine around the operator-owned handler.

On a recognized challenge WohnWerk must:

1. identify the exact `CrawlRun`, shard, region, price band and navigation point;
2. persist cumulative page/card/unique-ID counters;
3. persist the same-run resume cursor;
4. persist the already selected fair shard order;
5. export browser storage state and diagnostic screenshot where available;
6. commit persistence before invoking the external handler;
7. mark the current run/shard paused without fabricating failures for untouched shards;
8. invoke the external handler through the documented JSON stdin/stdout contract;
9. on `resolved`, load returned/updated browser state and retry the same saved navigation point in the same run;
10. on `defer`, leave the run unfinished and resumable;
11. on `abort`/hard source failure, count the actual failed work separately and mark untouched remainder as skipped/not-attempted;
12. never allow a challenge-resumed/incomplete run to gain reconciliation authority unless complete identity history and all normal authority conditions hold.

The supported operator boundary is exposed through `--challenge-handler` and/or
`WOHNWERK_IMMOWELT_CHALLENGE_HANDLER`. The request carries `contract_version=1`; newly created
handoffs also carry a stable `handoff_id`. Persisted legacy handoffs such as Run #990 remain
backward compatible even if that field is empty.

The child process receives only the documented allowlisted execution environment plus
`WOHNWERK_CHALLENGE_CONTRACT_VERSION=1`; unrelated WohnWerk runtime variables are not forwarded.

See `docs/immowelt_handler_contract.md` for the concrete JSON contract and acceptance checklist.

The handler itself is not a WohnWerk implementation task.

### Latest production Immowelt checkpoint

The last important live experiment is **Run #990**.

Observed state:
- run status: `paused`
- coverage: `degraded`
- 2 of 48 shards completed before the active challenge point
- 4 pages fetched
- 160 items seen
- 93 new
- 67 updated
- actual failed shards: 0
- paused shard: 1
- untouched work was not fabricated as failure
- persisted handoff state exists under the run/shard challenge-state hierarchy

Do not discard this state merely to restart from page 1.

As of v0.4.2, Run #990 is retained for audit/diagnostic continuity but is **not resume-compatible** with the current Germany shard contract because it was created under the legacy EUR 30,000..300,000 price partition. Do not resume it under v0.4.2. The launcher detects the persisted shard mismatch rather than silently reusing incompatible state. Do not delete the run merely because it is incompatible.

## Current Germany house product requirements

The operator confirmed these requirements on 2026-09-26. They are product targets; do not claim an item is implemented until code/data/runtime proof exists.

### Acquisition/filtering

- Purchase target: EUR 30,000..200,000.
- Auction / `Versteigerung` houses are unacceptable.
- Broad acquisition should collect houses inside the configured price range rather than encode subjective local preferences into source queries.
- PLZ blacklist, hospital distance and similar suitability rules are evaluated locally.
- If an auction can be excluded cleanly at source, exclude it; otherwise retain discovery evidence but locally reject it.
- Locally rejected houses remain inspectable in a separate rejected/filtered view.
- Every rejected house card shows explicit understandable reason tags.

### Location filters

- Add user-managed German PLZ blacklist.
- Support exact 5-digit PLZ plus wildcard masks such as `0xxxx`.
- `x` / `X` represents one decimal digit after PLZ normalization.
- Add region browsing through a center `PLZ/Ort` plus configurable N-km radius.
- Add a configured workplace location for the father.
- House details show distance to that workplace.
- Workplace distance is a decision factor rather than a daily-commute hard reject by default because work is mostly home office with roughly two office visits per month.

### Hospital access — v0.4.5 deployed

- Bundes-Klinik-Atlas Open Data is the current DE hospital source.
- Nearby hospital access is derived only from source-backed facility coordinates.
- House UI shows defensible air distance and source-backed hospital identity/type/capability.
- Confirmed Notfallstufe 1–3 is distinguished from unagreed/unknown emergency level.
- Capability modules are shown separately and are never inferred from a generic hospital name.
- A configurable maximum confirmed-emergency distance is part of local suitability/rejection, not source lifecycle.
- Missing hospital evidence remains unknown/fail-open unless the operator explicitly configures fail-closed behavior.
- Dataset authority requires `coverage_status=ok`; incomplete/failed imports do not gain rejection authority.

### Internet — v0.4.6 deployed baseline

- Official DE fixed-network evidence comes from Breitbandatlas | Gigabit-Grundbuch snapshot 2025-12-31.
- Dataset authority is explicit and currently `coverage_status=ok`.
- A property is matched to a 100×100 m grid cell only when its coordinate provenance/precision is defensible for that grid.
- Current portal ingestion supplies PLZ-centroid coordinates, so current property-level fixed-Internet evidence correctly remains unknown rather than selecting a nearby cell.
- Public grid values remain percentages of covered households, not Boolean exact-house availability.
- Price/provider stay unknown without a separate source.
- Starlink is a separate fallback concept, never terrestrial coverage.
- Next Internet work may add source-backed exact-address/coordinate extraction and description/portal Internet evidence; any predictive model must be presented as an estimate distinct from source evidence.

### Property quality

- Improve conservative duplicate detection across sources.
- Preserve every source listing/provenance beneath the canonical property.
- Capture/display source-backed heating type such as oil, electric or wood.
- Wood heating is a positive preference.
- Unknown heating remains unknown.

## Germany price/auction policy — v0.4.2 candidate

The v0.4.2 implementation changes the Germany acquisition contract to:
- 48 shards remain (16 regions x 3 bands);
- bands are `030000-099999`, `100000-149999`, `150000-200000`;
- the exact covered range is EUR 30,000..200,000 with no gaps or overlaps;
- Immowelt requests `distributionTypes=Buy` only;
- explicit `Versteigerung` / auction markers that still leak into discovery are retained as source evidence but locally rejected with reason `auction`;
- DE product visibility uses a country-aware EUR 200,000 ceiling while legacy/AT behavior remains at EUR 300,000;
- historical DE rows above EUR 200,000 remain stored for lifecycle/provenance but are no longer father-visible;
- no migration or destructive cleanup is required.

Run #990 was created under the old 30,000..300,000 shard contract. Its persisted state is retained,
but the v0.4.2 launcher treats that paused run as shard-contract-incompatible and will not
auto-resume it. This satisfies the earlier rule to resume it only if persisted state remains
compatible; the new price policy deliberately makes that condition false.

## Local suitability/rejection — v0.4.3 deployed

The deployed v0.4.3 release introduces migration `0013_candidate_house_policy` and keeps suitability separate from source lifecycle:

- one profile-scoped persisted Germany PLZ blacklist;
- exact five-digit PLZ and `x`/ `X` masks, with one wildcard digit per `x`;
- normal father-facing house views require both source product visibility and local PLZ suitability;
- a separate `Abgelehnt` view shows current canonical houses rejected by source policy and/or local PLZ policy;
- rejected cards carry multiple German reason tags and retain original source links;
- rejection does not mutate `Property.status`, `PropertyListing.status`, reconciliation authority or provenance;
- favorite/hidden/viewed state remains orthogonal and survives rejection/policy changes;
- DE PLZ blacklist does not apply to Austria;
- the already implemented `PLZ/Ort + N km` PostGIS/GeoNames path remains the radius browse mechanism and is regression-covered rather than duplicated.

## Workplace distance — v0.4.4 deployed

The deployed v0.4.4 release introduces migration `0014_candidate_workplace`:

- one workplace row per candidate profile, independent of German job acquisition;
- explicit workplace country `DE` or `AT` plus preserved operator input;
- an address containing a compatible PLZ resolves only to the imported PLZ centroid and is labelled `explicit_postal_centroid`; no street-precision claim is made;
- locality-only input uses the existing country-scoped locality resolution path;
- unresolved input remains stored with no coordinate and an explicit error; no coordinate is invented;
- catalogue cards and accepted house details show workplace Luftlinie when defensible;
- road distance/driving time are optional refinements from the existing OSRM table service and fall back cleanly to Luftlinie when routing has no coverage;
- workplace distance is not part of `accepted_property_condition` / `rejected_property_condition` and therefore is not a hard reject by default;
- Germany job acquisition stays paused and no job listing is used as the workplace source.

## Near-term roadmap

1. **DONE:** v0.4.1 scheduler/docs/handler-boundary hardening deployed and production-verified at `0890f0283e217b84a9de37e418a6fb6677391c66`.
2. **DONE:** v0.4.2 Germany EUR 30,000..200,000 + non-auction policy deployed and production-verified at `88d578ca191071eba6bc2ab0ccbe466f9f966b3a`.
3. **DONE:** v0.4.3 local suitability/rejection layer deployed and production-verified at `f9d7e994c6264053c77d9e06c0f4eb586e92ea8f`, DB head `0013_candidate_house_policy`.
4. **DONE:** v0.4.4 workplace configuration/distance deployed and production-verified at `4472cb160f7f599e5c956d22b03bbcf299c4e556`, DB head `0014_candidate_workplace`.
5. **DONE:** v0.4.5 hospital-access enrichment deployed and production-verified at `e1b42a425e469a291298196f25b54a328341da86`, DB head `0015_hospital_access`, Bundes-Klinik-Atlas snapshot 2026-09-01 with 1,572 facilities and `coverage_status=ok`.
6. **DONE:** v0.4.6 DE Internet enrichment deployed and production-verified at `7e636b6edd80a1db0e56c160fc383c5630121008`, DB head `0016_internet_access`, Breitbandatlas snapshot 2025-12-31 with 3,590,703 grid cells and `coverage_status=ok`.
7. **DONE:** v0.4.7 house settings modal/UI cleanup deployed and production-verified at `a1423e7aee4c59c61508f54e74f1cdfc20a9948b`; no DB migration.
8. **DONE:** v0.4.8 deeper Internet source-evidence work shipped as part of the atomic v0.4.9 production release.
9. **DONE:** v0.4.9 multi-source/dedupe/heating release deployed at `3debfc67d4a828c418cab35b921f0412cbb2a26b`:
   - Kleinanzeigen bounded newest-first frontier is operational;
   - conservative cross-source canonical dedupe is active;
   - source-backed heating is displayed, with Holz marked preferred and unknown preserved;
   - ImmoScout24 has explicit challenge checkpoint/handoff semantics but remains unscheduled;
   - VON POLL code remains available but its production source is disabled after a live HTTP-403 access gate.
10. **DONE:** v0.4.10 r4 deployed at `3ba1dae99c190ff3089c6dfdebdafd1233509b2e`: Engel & Völkers frontier, heating integration, conservative unique-city PLZ resolution, DE source-card previews and shared categorized/icon-based house facts.
11. **DONE:** v0.4.11 deployed and production-accepted at `6d7fd14cefbff75bed3957a5443c419c04db8501`: branded provenance badges, s REAL location hardening, targeted persisted repair and live acceptance of property 62724 at 2225 Loidesthal.
12. **DONE:** v0.4.12 deployed and production-accepted at `96656cd96091b33944824e5cb1b003142e7012d8`: `iad-de` is operational with 9 new bootstrap listings; `remax-de` is explicitly fail-closed/unscheduled after target-host Cloudflare Turnstile detection.
13. **CURRENT:** continue evaluating additional independent broker/regional sources only where they add inventory rather than merely alias existing portals.
14. Keep Germany jobs paused until an explicit operator decision reopens them.
15. Keep the external challenge-handler implementation untouched. Run #990 remains retained and incompatible with the newer Immowelt shard contract.

## Fresh-context recovery order

1. `HANDOFF.md`
2. `docs/germany_mvp.md`
3. `docs/requirements.md`
4. `docs/acquisition.md`
5. `docs/sources.md`
6. inspect current PR/branch HEAD and exact-head CI before any mutation

Do not infer the active task from the old Austria deployment history or from dormant Germany job code.
