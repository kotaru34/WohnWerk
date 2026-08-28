# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-28 (Europe/Berlin)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This is the authoritative recovery point for a fresh context.

## Product invariants

WohnWerk is a private/self-hosted Austria-first property + job acquisition, personalization and matching system for the candidate/father.

- App/user UI is German-only.
- Source lifecycle, discovery relevance and candidate fit are separate concerns.
- Failed/partial crawls never mass-deactivate authoritative data.
- Missing from a frontier search is not proof of disappearance.
- Hidden/favorite curation survives lifecycle/canonical merges.
- Do not invent coordinates or semantic property attributes.
- Geography/commute remains separate from intrinsic job fit.
- No permanent Job×Property pair table unless future measurements justify it.

## Production runtime

Public URL: `https://wohnwerk.kotaru.lainlounge.org`

- Caddy -> `127.0.0.1:8000`
- `wohnwerk.service`: Uvicorn/FastAPI, loopback only
- local OSRM: `127.0.0.1:5000`, Austria graph, MLD, mmap
- `wohnwerk-refresh.timer`: every 15 minutes, dynamic source refresh
- `wohnwerk-liveness.timer`: daily frontier liveness probe
- health endpoint: `/health`

Latest verified runtime after the IMMMO repair:
- web service active and listening on 127.0.0.1:8000
- `/health` returns `status=ok`, `country=AT`
- refresh timer active/waiting with a real next trigger

Existing Starlette warning is non-blocking: `starlette.testclient`/`httpx` deprecation.

## Property acquisition and lifecycle

Authoritative property sources:
- `immmo.at`
- `sreal.at`

ImmoAds remains disabled.

Lifecycle model:
- `ListingStatus`: ACTIVE / INACTIVE / UNKNOWN
- source listing first/last seen timestamps and inactive timestamp
- canonical property lifecycle is derived conservatively from source listings
- reconciliation disappearance requires consecutive complete/OK scans
- incomplete scans cannot mass-deactivate

### IMMMO identity continuity — CLOSED

IMMMO is a meta-search source. Its downstream portal URL is not stable identity: the same physical property can rotate between ImmobilienScout24, FindMyHome, Nachrichten, SN and synthetic IMMMO fallback URLs.

Continuity implementation:
- `app/ingestion/property_continuity.py`
- `app/ingestion/immmo_continuity.py`
- `scripts/repair_immmo_continuity.py`

Current continuity policy: `immmo-continuity-2026-08-28-v3`.

Safe strategies only:
- exact: PLZ + normalized title + price + provider-neutral display-area fingerprint
- title_area: PLZ + normalized title + display-area fingerprint

Price-only continuity was removed because provider changes can also change area semantics.

Run #47 historical repair:
- raw new: 2267
- deterministic continuity matches: 1471
- reclassified genuinely-new rows: 1466
- effective new after repair: 801

v3 idempotency verification on run #47:
- `deterministic_pairs=0`

Subsequent full scans stabilized naturally; latest controlled scans had no identity churn (`new=0`, `continuity_merged=0`). Do not reopen continuity unless new production evidence shows a concrete regression.

## IMMMO area semantics — CLOSED

Critical source fact: IMMMO's card-level `PLZ / N m²` is a provider-defined display area. It can represent Wohnfläche, Nutzfläche or Grundstück depending on the downstream portal/card. It must not be blindly stored as Wohnfläche.

Current parser payload format: `immmo-search-discovery-v12`.

Current semantics:
- explicit Wohnfläche / Wohnnutzfläche -> canonical `living_area_m2`
- explicit Grundstück / Grundstücksfläche -> `plot_area_m2`
- generic primary card area -> `raw_payload.display_area_m2`
- ambiguous display area is not promoted to Wohnfläche

Parser v12 also protects flattened metadata such as:
- `Wohnnutzfläche: 87.75 m² Grundstücksfläche: 410 m²`
- `Nutzfläche: 120 m² Grundstücksfläche: 784 m²`
so a previous numeric field is not incorrectly attached to the next label.

Run #62 full v12 reconciliation:
- status success / coverage ok
- rows seen: 13,990
- new: 0
- continuity merged: 0
- disappeared: 1
- explicit living: 6,112
- explicit plot: 3,030

Historical legacy repair: `immmo-area-semantics-2026-08-28-v2`.

The controlled repair cleared 7,395 IMMMO-only canonical `living_area_m2` values whose current audited v12 listings had no explicit living-area evidence. Source/display values were retained in listing raw payload; repair metadata records the previous canonical value.

Repair checks:
- safety dry-run candidates: 7395
- applied: `canonical_living_cleared=7395`
- repeat dry-run: `unverified_immmo_only=0`

Post-repair audit on run #62:
- canonical_living_mismatch=0
- suspicious_plot_as_living=0
- suspicious_immmo_only=0
- unverified_canonical_living=0
- unverified_immmo_only=0

UI semantics now support neutral `Fläche N m² (Typ nicht eindeutig)` when canonical Wohnfläche is unknown but a single unambiguous source display-area exists. Do not call this value Wohnfläche.

## Jobs, concepts and candidate fit

Current relevant active jobs: 179.

Candidate profile:
- slug: `mechanical-project-engineer`
- label: `Maschinenbau / technische Projektleitung`
- father profile: ~30 years mechanical engineering / technical project leadership, product development, mechanical design, project steering, machinery/vehicle/rail/special equipment, team/vendor/specification/schedule/FEM/FMEA/test/assembly/commissioning experience

Current fit policy: `candidate-fit-2026-08-28-v3`.

Concept extractor: `concept-seed-2026-08-28-v3`.

Candidate curation:
- migration `0009_candidate_job_preferences`
- sparse favorite/hidden per profile
- hidden is recoverable
- favorite does not intrinsically boost fit
- canonical merge OR-preserves curation

Previously hidden by user and excluded from matching:
- job #205 HR Group
- job #214 ACTIEF JOBMADE

Matching excludes hidden, hard-incompatible and unscored jobs before geography.

## Dynamic refresh

Authoritative reconciliation sources:
- immmo.at
- sreal.at
- lever-public-postings
- personio-public-xml
- smartrecruiters-public-postings

Frontier job sources:
- karriere.at
- jobs.at
- stepstone.at
- willhaben-jobs

Scheduler runs every 15 minutes and decides source due-ness from DB state. Job success triggers resolver/concept processing and live fit remains recomputable.

Known future acquisition expansion:
- Workday
- Greenhouse
- direct Austrian company career pages
- additional Austrian job sources where useful

## Geography and routing

Property location semantics:
- Austrian BEV PLZ centroid

Job location semantics:
- explicit PLZ centroid where available
- otherwise conservative locality centroid
- unresolved/countrywide remains ungeocoded

Road semantics:
- PostGIS geography is the cheap Luftlinie prefilter
- local OSRM Table API performs fastest-driving refinement
- 50 km configured radius is enforced on road distance after refinement
- prefilter default: 75 properties/job
- same-PLZ/same-centroid pairs can legitimately report 0 km / 0 min; this is a centroid limitation, not a routing failure

Latest post-repair road audit (50 km, 20 jobs, 5 houses/job, prefilter 75):
- routing_status=ok
- routing_seconds=0.749
- active_properties=14,414
- located_properties=14,413
- property_location_ratio≈1.000
- relevant_jobs=179
- relevant_job_locations=190
- located_job_locations=159
- jobs_with_located_location=151
- job_location_ratio=0.844

The routing layer remains fast and healthy after the property cleanup.

## Current UI state

Current protected German surfaces:
- `/admin/matches` — job + nearby-house combinations
- `/admin/jobs` — ranked jobs, filters, favorite/hide actions
- `/admin/concepts` — technical candidate concept review/admin

Root currently redirects to the matching surface.

The matching page is already road-aware and fail-soft to Luftlinie. Property area presentation is provenance-aware after the v12 repair.

## Immediate next steps

1. Move father-facing browsing away from the `/admin/*` namespace without rewriting the proven auth/curation internals:
   - `/matches` for combinations
   - `/jobs` for ranked jobs and favorite/hide curation
   - keep `/admin/concepts` as the technical/admin surface
   - preserve legacy `/admin/matches` and `/admin/jobs` compatibility redirects/aliases
2. Make root `/` lead to `/matches`.
3. Add `Kombinationen` + `Stellen` navigation consistently on father-facing pages; do not surface `Konzepte` as a normal user tab.
4. Keep Basic auth for now; improve auth naming/UX separately if needed.
5. After father-facing navigation is stable, continue broad job acquisition (Workday/Greenhouse/direct career pages).
6. Later improve location precision only with source-backed street/address evidence; do not fake street-level routing from centroids.
