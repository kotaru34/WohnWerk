# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-09-26  
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

Production baseline before this development step:

- application version: **v0.4.0**
- database migration: `0012_de_postal_codes`
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

Current development target is **v0.4.1**.

The v0.4.1 step:
- removes `adzuna-api-de` and `arbeitsagentur-jobsuche-de` from automatic refresh plans;
- adds regression coverage that DE job sources are not scheduled;
- records the house-only Germany scope and new house requirements;
- does not modify the external challenge-handler implementation.

The last fully green pre-v0.4.1 PR #5 HEAD was
`4b8522c47065871a84343e229ef65fd95d08161e`, GitHub Actions CI #1213:
Install + Ruff + Compile + Tests, **590 passed, 3 warnings**.

The current v0.4.1 development HEAD must receive its own exact-head green CI before any production mutation.

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
`WOHNWERK_IMMOWELT_CHALLENGE_HANDLER`.

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

When the operator finishes the external handler, first validate the WohnWerk-side integration contract, then resume **the same Run #990** if the persisted state is still compatible. Do not start a replacement crawl just to avoid using the resume path.

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

## Current implementation gap: Germany price shards

The current portal implementation still carries the earlier EUR 30,000..300,000 48-shard price partition.

That is now legacy implementation state, not the product requirement.

Before the next authoritative Germany property acquisition cycle:
- reduce the acquisition ceiling to EUR 200,000;
- rebalance shard boundaries as needed to stay below source result/safety caps;
- keep the price partitions non-overlapping;
- add regression tests for the new range;
- ensure historical rows above EUR 200,000 are locally excluded/rejected according to the new product policy rather than corrupting lifecycle evidence.

## Near-term roadmap

1. **CURRENT:** finish v0.4.1 source-scheduler/docs step and obtain exact-head green CI.
2. Obtain a shell-enabled Sentinel authorization before production deployment/diagnostics; a prior relay authorization lacked shell permission and Sentinel correctly denied even a read-only `git status`.
3. Deploy exact green v0.4.1 to the WohnWerk VM.
4. On production, verify German job sources are not due/scheduled; disable their Source rows as an additional operational guard if appropriate while preserving historical records.
5. Verify Austria acquisition/timers remain healthy after the scheduler change.
6. Next house implementation step: change Germany acquisition budget/shards to EUR 30,000..200,000 and make auction semantics explicit.
7. Then implement local house suitability/rejection infrastructure (reason codes + rejected view + PLZ blacklist/radius).
8. Add workplace-distance, hospital and Internet enrichment in evidence-backed slices.
9. Improve dedupe and heating-type extraction/ranking.
10. Keep the external handler untouched. When the operator declares it ready, validate the integration boundary and resume Run #990.

## Fresh-context recovery order

1. `HANDOFF.md`
2. `docs/germany_mvp.md`
3. `docs/requirements.md`
4. `docs/acquisition.md`
5. `docs/sources.md`
6. inspect current PR/branch HEAD and exact-head CI before any mutation

Do not infer the active task from the old Austria deployment history or from dormant Germany job code.
