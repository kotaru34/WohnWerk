# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-30 (Europe/Berlin)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This is the authoritative recovery point for a fresh context.

## Current release state

- Production is verified through **v0.3.15**.
- Current branch target is **v0.3.16 observability maintenance** after the first validated Workday import.
- Father has used the service continuously for several days and reports that it is stable and useful.
- Product work should favor evidence-driven maintenance and acquisition quality over speculative rewrites.
- Exact-head GitHub CI success is a hard production deployment gate.

## Product invariants

WohnWerk is a private/self-hosted Austria-first property + job acquisition, personalization and matching system for the candidate/father.

- App/user UI is German-only.
- Father-facing product has two independent catalogs: **Häuser** and **Stellen**.
- Source lifecycle, discovery relevance and candidate fit are separate concerns.
- Failed/partial crawls never mass-deactivate authoritative data.
- Missing from a frontier search is not proof of disappearance.
- Disabled sources must never contribute father-visible jobs.
- Hidden/favorite/viewed curation survives lifecycle/canonical merges.
- Never invent coordinates, images, prices or semantic property attributes.
- Geography/commute remains separate from intrinsic job fit.
- No permanent Job×Property pair table unless future measurements justify it.

## Production runtime

Public URL: `https://wohnwerk.kotaru.lainlounge.org`

- Caddy -> `127.0.0.1:8000`
- `wohnwerk.service`: FastAPI/Uvicorn, loopback only
- local OSRM: `127.0.0.1:5000`, Austria graph, MLD, mmap
- `wohnwerk-refresh.timer`: dynamic source scheduler wake-up every 15 minutes
- `wohnwerk-images.timer`: image/detail maintenance
- `wohnwerk-liveness.timer`: property liveness maintenance
- `/health`: lightweight service health/version endpoint
- `/admin/health`: protected Betrieb/source-value overview
- `/admin/concepts`: protected concept administration with the same top navigation/style as Betrieb

Existing Starlette TestClient/httpx deprecation warning is non-blocking.

## Father-facing UX

Normal navigation:
- `/houses`
- `/jobs`

Root `/` redirects to `/houses`.

### Houses

`/houses` provides pagination, price/location/verified-area filters, sorting, source-backed images only, semantic area display, favorite/hide/viewed curation and `Bei WohnWerk seit` dates.

`/houses/{id}` provides details, original source links and nearby eligible jobs.

Descriptions may remain stored internally but are intentionally not shown unevenly in the father-facing house UI.

### Jobs

`/jobs` provides intrinsic candidate fit, salary/source/location data, favorite/hide/viewed curation, sorting/filters and `Bei WohnWerk seit` dates.

`/jobs/{id}` provides source links and nearby houses.

Hourly salary rows remain missing-last in annual salary sorting unless defensible working-hours evidence exists; never invent an annual equivalent.

Father-facing job visibility requires all of:
- canonical `Job` active
- at least one `JobListing` active
- source enabled
- persisted `wohnwerk_discovery_gate.accepted == true`

## Property acquisition and semantics

Authoritative property sources:
- `immmo.at`
- `sreal.at`

ImmoAds remains disabled.

### IMMMO continuity

Current continuity policy: `immmo-continuity-2026-08-28-v3`.

Safe continuity strategies only:
- PLZ + normalized title + price + provider-neutral display-area fingerprint
- PLZ + normalized title + display-area fingerprint

Historical deterministic repair is complete and idempotent. Do not reopen without concrete production evidence.

### Property dedupe / areas / images

Cross-source property dedupe remains conservative: compatible PLZ, exact price, strong normalized-title identity and no conflicting explicit area evidence.

Area semantics:
- explicit Wohnfläche/Wohnnutzfläche -> living area
- explicit Grundstück/Grundstücksfläche/Grundfläche -> plot area
- explicit Nutzfläche -> usable area
- generic source area -> neutral display-only `Fläche`

Images are exact listing-backed only. Never title-search the web for a substitute.

Known repaired production controls include the ImmoScout area/price cases, FindMyHome area cases, the wrong-image case and the deterministic Neuhofen duplicate merge from earlier checkpoints.

## Property liveness

Two layers exist:

1. Global conservative maintenance sweep.
2. Visible-page liveness: `/houses` schedules non-blocking checks for rendered listings older than roughly 30 minutes.

Definitive 404/410/provider removed evidence can deactivate an observation. 403/CAPTCHA/429/timeouts/network uncertainty do not hide previously live listings. Repeated page refreshes are deduplicated.

## Candidate profile and discovery

Candidate profile:
- slug `mechanical-project-engineer`
- label `Maschinenbau / technische Projektleitung`
- roughly 30 years mechanical engineering / technical project leadership experience

Current discovery gate in production: **`profile-seed-2026-08-30-v18`**.

The discovery gate is a high-recall professional-neighborhood filter, not the candidate-fit score. Obvious software/IT, academic/student, generic unsolicited applications, manual-production trades, logistics/procurement and other structural false positives must be rejected before persistence/fit.

Recent production regressions now covered by tests include:
- Greenhouse software/QA false positives
- pure building/electrical false positives without relevant mechanical/vehicle domain
- CNC turning/milling trades
- laboratory technician roles
- Workday academic thesis / Initiativbewerbung
- Workday `Program / Project Responsible IT`
- Workday packaging/logistics planning

Legitimate adjacent engineering such as automotive electrical systems, supplier quality development, commissioning, plant planning and manufacturing engineering must remain eligible for fit ranking.

## Production job sources

Enabled/operational:
- `karriere.at` — bounded discovery frontier; no disappearance authority
- `jobs.at` — bounded discovery frontier; no disappearance authority
- `stepstone.at` — bounded discovery frontier; no disappearance authority
- `willhaben-jobs` — bounded discovery frontier; no disappearance authority
- `lever-public-postings` — tenant feeds; reconciliation-capable where complete
- `personio-public-xml` — complete tenant feeds; reconciliation-capable
- `smartrecruiters-public-postings` — tenant feeds; reconciliation-capable when full coverage is obtained
- `workday-public-cxs` — **production-validated in v0.3.15**, discovery-only, no disappearance authority

### Workday production validation

Validated tenants:
- `kiongroup:KIONGroup` — KION Group / Linde Material Handling
- `magna:Magna` — Magna

First controlled production import in v0.3.15:
- 12/12 shards successful
- 8 persisted relevant listings
- 4 KION + 4 Magna
- all persisted rows carried gate v18 `accepted=true`
- all imported source-backed locations resolved successfully
- source enabled only after persisted-corpus and geo audit

Accepted examples include KION AGV commissioning/service engineering and Magna chassis development, supplier quality development, electric propulsion/electronics and body-shop plant planning.

Workday search-text shards are discovery frontiers only. Never use absence from one query union as disappearance proof.

### SmartRecruiters

Production tenant expansion is valuable and currently includes the earlier base tenants plus IMS Nanofabrication, Anton Paar, Umdasch/Doka and Kronospan/Kaindl where operator state is enabled.

v17 reclassified known false positives such as `CNC-Dreher/-Fräser` and `Labortechniker` while preserving legitimate manufacturing/quality engineering.

### Personio candidate note

`beyondcarbon-energy` remains disabled because the tested Personio XML endpoints returned 404. Do not force it through the Personio XML adapter; use a future direct-source adapter only if coverage value justifies it.

### Greenhouse

`greenhouse-public-job-board` remains **disabled**.

The first bootstrap exposed software/QA/building/electrical false positives; stale rows were purged, disabled-source visibility was fixed, and subsequent gates narrowed the corpus. Re-evaluate Greenhouse only with a clean live preflight and no father-facing import before approval.

### Lever

Keep the adapter. Current tenant set has comparatively low yield/value, so future effort should focus on better tenant discovery rather than rewriting the adapter.

## Job geography

Principles:
- explicit source PLZ wins
- otherwise conservative locality centroid
- broad Bundesland/country labels remain unresolved rather than receiving a fake center
- approximate area labels use explicit semantics/provenance only

Implemented repairs include Salzburg-area semantics, Oberösterreich Zentralraum, Niederranna PLZ evidence, punctuation-safe locality matching (`St. Valentin`, etc.), jobs.at visible-header repair, Salzburg Stadt/Vienna district handling and conservative `X bei Y` fallback.

Current intentionally unresolved examples include:
- `Standort: Tirol (Außendienst & Homeoffice)`
- `österreichweit`
- `Wels-Land`
- `Schaftenau`
- `Ranshofen`
- `AT`
- `Graz Umgebung-West`
- `Traboch`

Do not force these to arbitrary coordinates without better source evidence/locality semantics.

## Routing

- PostGIS geography handles scalable straight-line prefiltering.
- local OSRM Table API provides road distance/time for displayed results.
- coordinates are centroid-level, not street-address precision.

## Source health semantics

Execution success and coverage authority are separate:

- all shards executed + complete coverage -> `run=success`, `coverage=ok`
- all shards executed + intentionally bounded/incomplete coverage -> `run=success`, `coverage=degraded`
- some shards actually failed -> `run=partial`, `coverage=degraded`
- all shards failed -> `run=failed`, `coverage=failed`

A bounded frontier run is not an operational failure.

`v0.3.12` added backward-compatible interpretation for legacy pre-v0.3.11 bounded partial runs so healthy sources do not remain yellow only because of historical status semantics.

## Operations / source value

`/admin/health` / Betrieb shows:
- active houses
- raw active canonical jobs
- father-visible relevant jobs
- unresolved non-remote job locations
- enabled sources
- per-source execution/coverage state
- latest run/status/items
- failing shards and last success/error
- top unresolved location labels
- active accepted listings per job source
- unique/exclusive/shared visible jobs
- latest accepted/rejected counts and gate yield

Use source-value evidence before adding/removing tenants or sources. A source should not be kept merely to inflate listing count.

## v0.3.16 maintenance target

After Workday production validation, two observability quirks were identified:

1. Workday CXS can report `total=0` on a later page even when the adapter materialized dozens of rows. `SourceBatch.source_reported_count` must never under-report the number of materialized source items.
2. Workday uses multiple search shards per tenant (`tenant:site:index`), while the registry key is `tenant:site`; successful shards must still update the tenant's `last_verified_at`.

These fixes are observability-only. They must not alter discovery/fit/lifecycle decisions or the validated 8-job Workday corpus.

## Approved near-term roadmap

Priority order from the current checkpoint:

1. Complete v0.3.16 observability maintenance and verify Workday tenant timestamps/count diagnostics.
2. Re-evaluate Greenhouse with the current v18 gate and clean preflight; enable only if live accepted families are defensible.
3. Improve Lever tenant discovery based on source-value evidence.
4. Add selected direct Austrian employer career pages only where they materially improve exclusive useful coverage.
5. Continue conservative geo cleanup only from real production unresolved labels/source evidence.
6. Implement real-time UI synchronization.

## Real-time UI synchronization TODO

Goal: no full page refresh should be required for:
- newly discovered/removed houses
- newly discovered/removed jobs
- `Neu` / no longer `Neu`
- viewed/unviewed
- favorite/unfavorite
- hidden/unhidden
- list counters/tabs
- `/admin/health` source/run/location metrics

Preferred first implementation for the current single-node FastAPI deployment:
- **Server-Sent Events (SSE)** for server -> browser invalidation/update notifications
- existing HTTP POST actions remain authoritative for user writes
- small client-side reconciliation/fetch of affected cards/counters after events
- Caddy-compatible keepalive/reconnect behavior
- event IDs/reconnect safety

Use WebSockets only if a genuine bidirectional low-latency protocol becomes necessary. Do not replace page reloads with aggressive JavaScript polling.

## Acquisition expansion rules

For every new job source:
- Austria-only filtering must be explicit.
- Base professional relevance stays separate from candidate fit.
- Prefer public documented/observable endpoints over browser automation.
- Preserve source identifiers and canonical source URLs.
- Reconciliation/liveness semantics must fail safely.
- Add parser/coverage regression tests before production enablement.
- New tenant seeds should be disabled by default unless already explicitly operator-enabled.
- Do not add a source merely to inflate listing count.

## Deferred / evidence-only work

- broader IMMMO image coverage beyond exact source-backed associations
- annualizing hourly salaries without explicit hours/week
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
6. verify `/health` and targeted production data controls

This rule exists because earlier iterations exposed transient red CI states that must never be treated as deployable.
