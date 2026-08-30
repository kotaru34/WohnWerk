# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-30 (Europe/Berlin)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This is the authoritative recovery point for a fresh context.

## Current release state

- Production is verified through `v0.3.11`.
- Branch target after this checkpoint: `v0.3.12` source-value observability.
- Father has used the service continuously for several days and reports that it is stable and useful.
- Product work should favor evidence-driven maintenance and acquisition quality over speculative rewrites.

## Product invariants

WohnWerk is a private/self-hosted Austria-first property + job acquisition, personalization and matching system for the candidate/father.

- App/user UI is German-only.
- Father-facing product has two independent catalogs: **Häuser** and **Stellen**.
- Source lifecycle, discovery relevance and candidate fit are separate concerns.
- Failed/partial crawls never mass-deactivate authoritative data.
- Missing from a frontier search is not proof of disappearance.
- Hidden/favorite/viewed curation survives lifecycle/canonical merges.
- Never invent coordinates, images, prices or semantic property attributes.
- Geography/commute remains separate from intrinsic job fit.
- No permanent Job×Property pair table unless future measurements justify it.
- Production deploys require a green GitHub CI run on the exact branch HEAD before a deploy command is handed to the operator.

## Production runtime

Public URL: `https://wohnwerk.kotaru.lainlounge.org`

- Caddy -> `127.0.0.1:8000`
- `wohnwerk.service`: Uvicorn/FastAPI, loopback only
- local OSRM: `127.0.0.1:5000`, Austria graph, MLD, mmap
- `wohnwerk-refresh.timer`: dynamic source refresh, scheduler wake-up every 15 minutes
- `wohnwerk-images.timer`: image/detail/liveness maintenance batches
- `wohnwerk-liveness.timer`: property liveness maintenance
- `/health`: lightweight service health/version endpoint
- `/admin/health`: protected operations/coverage overview

Existing Starlette TestClient/httpx deprecation warning is non-blocking.

## Father-facing UX

Normal navigation:
- `/houses`
- `/jobs`

Root `/` redirects to `/houses`.

### Houses

`/houses` is the independent property catalog with:
- pagination
- price/location/verified-area filters
- sorting by price, novelty and viewed state, asc/desc
- source-backed images only
- explicit `Wohnfläche`, `Nutzfläche`, `Grundstück` when semantically verified
- neutral `Fläche` for unresolved source display-area semantics
- favorite/hide/viewed curation
- `Bei WohnWerk seit DD.MM.YYYY`

`/houses/{id}` provides property details, original source links and nearby eligible jobs.
Descriptions may remain stored internally but are intentionally not shown unevenly in the father-facing house UI.

### Jobs

`/jobs` provides:
- intrinsic candidate fit
- salary/source/location data
- favorite/hide/viewed curation
- sorting and filters
- `Bei WohnWerk seit DD.MM.YYYY`

`/jobs/{id}` provides source links and nearby houses.

Hourly salary rows remain missing-last in annual salary sorting unless defensible working-hours evidence exists; do not invent an annual equivalent.

## Property acquisition, identity and semantics

Authoritative property sources:
- `immmo.at`
- `sreal.at`

ImmoAds remains disabled.

### IMMMO continuity

Current continuity policy: `immmo-continuity-2026-08-28-v3`.

Safe continuity strategies only:
- PLZ + normalized title + price + provider-neutral display-area fingerprint
- PLZ + normalized title + display-area fingerprint

Historical deterministic repair was completed and verified idempotent. Do not reopen this without a concrete production regression.

### Cross-source property dedupe

A conservative cross-source merge exists for deterministic duplicates such as the same s REAL property syndicated through IMMMO/Nachrichten.

Merge requirements remain strict:
- compatible PLZ
- exact price
- sufficiently strong normalized title identity
- no conflicting explicit area evidence

Curation and source/image state must survive merges.

### Area semantics

Do not infer semantic area type from a generic card number.

Verified mappings include:
- explicit Wohnfläche/Wohnnutzfläche -> `living_area_m2`
- explicit Grundstück/Grundstücksfläche/Grundfläche -> `plot_area_m2`
- explicit Nutzfläche -> detail usable area, not Wohnfläche
- generic source area -> display-only neutral `Fläche`

Current detail-facts policy supports provider-native extraction from ImmoScout24 and FindMyHome, including structured GraphQL/visible page facts where source semantics are explicit.

Known production controls already fixed:
- ImmoScout `6a91...`: usable 83.38, plot 785, living remains null
- ImmoScout `6a5f79...`: living 86, usable 120, plot 1522
- promotional-title listing `6579...`: true purchase price 573500; excluded by max-price policy
- FindMyHome `5657040`: living 91, plot 653
- FindMyHome `5640125`: living 90, plot 566

## Property images

Policy: exact listing-backed images only. Never title-search the web for a substitute.

- s REAL exact image extraction is supported.
- provider detail enrichment can persist exact `primary_image_url`.
- local image cache is used by the catalog.
- targeted authoritative refresh exists for wrongly associated cached images.

A production wrong-image case (`6a8d...`) was repaired by re-reading the exact ImmoScout listing and refreshing the cache, not by manual image substitution.

## Property liveness

Two layers exist:

1. Global safety sweep: conservative maintenance scan.
2. Visible-page liveness: `/houses` schedules a background check for listings rendered on the current page when their last check is older than roughly 30 minutes.

Important semantics:
- page response is not blocked by source HTTP requests
- definitive 404/410/provider removed markers can deactivate an observation
- 403, CAPTCHA, 429, timeouts and transient network errors do not hide previously live listings
- repeated page refreshes are deduplicated to avoid source hammering

This behavior exists because the father repeatedly revisits houses within the same day and stale dead listings were operationally annoying.

## Jobs and candidate fit

Candidate profile:
- slug `mechanical-project-engineer`
- label `Maschinenbau / technische Projektleitung`
- roughly 30 years mechanical engineering / technical project leadership experience

The fit model is concept-based and separates hard incompatibility from intrinsic fit and geography.

Father-facing job visibility requires all of:
- canonical `Job` active
- at least one `JobListing` active
- source enabled
- persisted `wohnwerk_discovery_gate.accepted == true`

This prevents disabled or rejected source rows from entering candidate fit.

### Production job sources

Enabled/operational:
- karriere.at — bounded discovery frontier, no disappearance authority
- jobs.at — bounded discovery frontier, no disappearance authority
- stepstone.at — bounded discovery frontier, no disappearance authority
- willhaben jobs — bounded discovery frontier, no disappearance authority
- Lever public postings — tenant feeds, reconciliation-capable where complete
- Personio public XML — complete tenant feeds, reconciliation-capable
- SmartRecruiters public postings — tenant feeds, reconciliation-capable when full coverage is obtained

Greenhouse public boards are implemented but currently **disabled** pending relevance-gate review. The first bootstrap exposed false-positive software/QA/electrical/building roles; stale rows were purged and disabled-source visibility was fixed in `v0.3.10`.

Existing Adzuna/Jooble adapters may be present in code but should not be treated as production coverage unless explicitly enabled/configured.

### Discovery gate

Current gate after the Greenhouse regression work is `profile-seed-2026-08-30-v16`.

Important principle: the discovery gate is a high-recall professional-neighborhood filter, not the candidate-fit score. Obvious software/IT/QA/building-service false positives must be rejected before persistence/fit.

Greenhouse preflight after v16 still admitted two GROPYUS electrical roles for manual review. Do not enable Greenhouse until those live cases are resolved safely without losing legitimate adjacent electrical/vehicle roles.

## Job geography

Principles:
- explicit source PLZ wins
- otherwise use a conservative locality centroid
- broad Bundesland/country labels remain unresolved rather than receiving a fake centre point
- approximate area labels may use an explicit named anchor only when provenance is retained

Implemented repairs include:
- `Salzburg Umgebung` / `Raum Salzburg` -> Salzburg anchor with approximate-area semantics
- `Oberösterreich Zentralraum` -> Linz/Wels/Steyr multi-locality centroid
- pure `Kärnten`, `Österreich`, etc. -> deliberately unresolved
- `Niederranna` source-backed PLZ 4085 from Karriere evidence, propagated conservatively
- punctuation-safe locality fallback fixes `St. Valentin`, `St. Gallen`, `Nußbach`, etc.
- jobs.at can repair broad structured region data from a concrete visible header locality
- `Salzburg Stadt` and Vienna district labels resolve conservatively
- `X bei Y` is accepted only when the base locality is unambiguous

Never force broad labels such as `AT`, `österreichweit`, Bundesländer or large regional sales territories into arbitrary centre coordinates.

## Routing

- PostGIS geography handles scalable straight-line inclusion/prefilter.
- local OSRM Table API provides road distance/time for displayed results.
- coordinates are centroid-level, not street-address precision.
- same-centroid pairs can legitimately display 0 km / 0 min.

## Source health semantics

Since `v0.3.11`, execution success and coverage authority are explicitly separate:

- all shards executed + complete coverage -> `run=success`, `coverage=ok`
- all shards executed + intentionally bounded/incomplete coverage -> `run=success`, `coverage=degraded`
- some shards actually failed -> `run=partial`, `coverage=degraded`
- all shards failed -> `run=failed`, `coverage=failed`

A bounded frontier run is therefore not an operational failure.

The production source sweep on 2026-08-30 verified:
- jobs.at: healthy frontier
- karriere.at: healthy frontier
- stepstone.at: healthy frontier
- willhaben: healthy frontier
- Personio: healthy complete feed
- Lever/SmartRecruiters/IMMMO/s REAL had old pre-v0.3.11 `partial/degraded` latest-run records with zero failed/unhealthy shards; these are legacy bounded-run semantics, not actual execution failures
- Greenhouse remains disabled/degraded by design

`v0.3.12` adds backward-compatible health interpretation so legacy bounded runs with all shards completed and zero failures no longer show as warnings when the source's authoritative coverage remains OK.

## Operations / source value

`/admin/health` shows:
- active houses
- raw active canonical jobs
- father-visible relevant jobs
- unresolved non-remote job locations
- enabled sources
- per-source execution/coverage state
- latest run/status/items
- active failing shards
- last success/error
- top unresolved location labels

`v0.3.12` also adds a **Wert der Stellenquellen** section with:
- active accepted source listings
- unique visible canonical jobs contributed by each source
- exclusive jobs only that source currently supplies
- jobs shared with another active accepted source
- accepted/rejected candidate counts from the latest run
- latest gate yield percentage

Use this evidence before adding/removing tenants or sources. A source should not be kept merely to inflate total listing count.

## Approved near-term roadmap

Priority order:

1. Keep `HANDOFF.md` current after meaningful production changes.
2. Use source-value/overlap data to tune current job sources and tenant registries.
3. Continue conservative geo cleanup from actual unresolved production labels.
4. Resolve the two remaining Greenhouse GROPYUS electrical false positives, then re-evaluate enabling Greenhouse.
5. Add Workday public career sites as a separate acquisition model after Greenhouse is stable.
6. Add selected direct Austrian employer career pages only where they materially improve useful coverage.
7. Add real-time UI synchronization so page reload is not required for catalog/admin state changes.

### Real-time UI synchronization TODO

Goal: updates should appear without a full page refresh for:
- newly discovered/removed houses
- newly discovered/removed jobs
- `Neu` / no longer `Neu`
- viewed/unviewed
- favorite/unfavorite
- hidden/unhidden
- list counters and tabs
- `/admin/health` source/run/location metrics

Preferred first implementation for the current single-node FastAPI deployment:
- **Server-Sent Events (SSE)** for server -> browser invalidation/update notifications
- existing HTTP POST actions remain authoritative for user writes
- small client-side reconciliation/fetch of affected cards/counters after an event
- Caddy-compatible keepalive/reconnect behavior
- event IDs / reconnect safety so a temporary connection drop does not leave stale UI

Use WebSockets only if a genuine bidirectional low-latency protocol becomes necessary. SSE is sufficient for the currently requested behavior and is operationally simpler.

Do not build this by polling every few seconds; the goal is lower reload/poll churn, not moving polling into JavaScript.

### Acquisition expansion rules

For every new job source:
- Austria-only filtering must be explicit.
- Base professional relevance filtering remains separate from candidate fit.
- Prefer public documented/observable endpoints over browser automation.
- Preserve source identifiers and canonical source URLs.
- Reconciliation/liveness semantics must fail safely.
- Add parser/coverage regression tests before enabling production tenants.
- Do not add a source merely to inflate listing count.

## Deferred / only if evidence justifies it

- broader IMMMO image coverage beyond exact source-backed associations
- automatic annualization of hourly salaries without explicit hours/week
- permanent Job×Property pair storage
- aggressive fuzzy property dedupe
- fake centroids for broad regions
- large UX redesign while father reports the current workflow works well

## Deployment discipline

For branch changes:

1. inspect final diff
2. wait for GitHub CI on the exact branch HEAD
3. require Install + Ruff + Compile + Tests success
4. only then provide production deployment commands
5. production still runs Ruff/compile/tests before restart
6. verify `/health` and targeted data controls

This rule exists because earlier iterations exposed transient red CI states that must never be treated as deployable.
