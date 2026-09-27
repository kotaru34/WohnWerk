# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-09-27  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active development branch:** `feature/immowelt-challenge-resume`  
**Base Germany branch:** `feature/germany`  
**Active draft PR:** #5 — `Make Immowelt challenges resumable and source-isolated`  
**Frozen Austria baseline:** `release/v1-austria` at `89f1833f`

This file is the authoritative recovery point for a fresh context. Read
`docs/germany_mvp.md` immediately after it, then `docs/requirements.md`,
`docs/acquisition.md` and `docs/sources.md`.

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

Production is now deployed on **v0.4.4**.

- deployed application version: **v0.4.4**
- deployed Git SHA: `4472cb160f7f599e5c956d22b03bbcf299c4e556`
- previous production Git SHA / rollback point: `f9d7e994c6264053c77d9e06c0f4eb586e92ea8f`
- local rollback ref: `refs/wohnwerk/rollback-v0.4.3-pre-v0.4.4`
- previous production application version: **v0.4.3**
- database migration: `0014_candidate_workplace`
- production host: migrated Debian 13 VM
- checkout/layout: `/opt/wohnwerk`, persistent state under `/var/lib/wohnwerk`
- database: remote HA PostgreSQL/PostGIS through multi-host libpq/psycopg with `target_session_attrs=read-write`
- PostGIS observed: 3.5.6
- local OSRM present
- Xvfb present for headed Immowelt Chromium
- public hostname: `wohnwerk.lainlounge.org`
- Caddy serves that explicit site
- production timers for refresh/images/liveness are intended to stay enabled during source experiments
- GeoNames DE postal import observed: 10,813 centroids
- Austria postal reference remained intact at the Germany bootstrap

v0.4.4 is deployed. The next implementation focus is **hospital-access enrichment** with source-backed facility identity/type/capability and defensible distance semantics. Internet enrichment follows after that.

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

### Hospital access

- Determine nearby hospital access where defensible.
- Show distance.
- Show source-backed hospital name/type/capability information useful for distinguishing ordinary/emergency-capable care.
- Do not infer emergency capability from a generic hospital label.
- Support a configurable maximum hospital-distance rule for local rejection.
- Missing hospital evidence remains unknown unless the operator explicitly configures fail-closed behavior.

### Internet

- Determine best available fixed Internet access as precisely as available house location/address permits.
- Show maximum defensible speed.
- Show price where source-backed.
- Never invent availability from coarse geography.
- Expose Starlink as an explicit fallback when terrestrial service is unavailable, insufficient or cannot be established under the configured rule.

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
5. **CURRENT:** add hospital-access enrichment with source-backed facility identity/type/capability and defensible distance semantics.
6. Then add Internet enrichment.
7. Improve dedupe and heating-type extraction/ranking.
8. Keep Germany jobs paused until an explicit operator decision reopens them.
9. Keep the external handler untouched. Run #990 is retained but no longer resume-compatible with the current shard contract.

## Fresh-context recovery order

1. `HANDOFF.md`
2. `docs/germany_mvp.md`
3. `docs/requirements.md`
4. `docs/acquisition.md`
5. `docs/sources.md`
6. inspect current PR/branch HEAD and exact-head CI before any mutation

Do not infer the active task from the old Austria deployment history or from dormant Germany job code.
