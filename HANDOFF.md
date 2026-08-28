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
- Father-facing product has two independent catalogs: **Häuser** and **Stellen**.
- Source lifecycle, discovery relevance and candidate fit are separate concerns.
- Failed/partial crawls never mass-deactivate authoritative data.
- Missing from a frontier search is not proof of disappearance.
- Hidden/favorite job curation survives lifecycle/canonical merges.
- Do not invent coordinates, images or semantic property attributes.
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

Latest verified runtime before the house-first UI deploy:
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

Run #47 historical repair:
- raw new: 2267
- deterministic continuity matches: 1471
- reclassified genuinely-new rows: 1466
- effective new after repair: 801

v3 idempotency verification on run #47: `deterministic_pairs=0`.
Subsequent full scans stabilized naturally; controlled scans had `new=0`, `continuity_merged=0`. Do not reopen continuity without concrete new production evidence.

## IMMMO area semantics — CLOSED

IMMMO's card-level `PLZ / N m²` is a provider-defined display area. It can represent Wohnfläche, Nutzfläche or Grundstück and must not be blindly stored as Wohnfläche.

Current parser payload format: `immmo-search-discovery-v12`.

Current semantics:
- explicit Wohnfläche / Wohnnutzfläche -> canonical `living_area_m2`
- explicit Grundstück / Grundstücksfläche -> `plot_area_m2`
- generic primary card area -> `raw_payload.display_area_m2`
- ambiguous display area is not promoted to Wohnfläche

Run #62 full v12 reconciliation:
- status success / coverage ok
- rows seen: 13,990
- new: 0
- continuity merged: 0
- disappeared: 1
- explicit living: 6,112
- explicit plot: 3,030

Historical repair: `immmo-area-semantics-2026-08-28-v2`.

Controlled repair:
- dry-run candidates: 7,395
- applied: `canonical_living_cleared=7395`
- repeat dry-run: `unverified_immmo_only=0`

Post-repair audit:
- canonical_living_mismatch=0
- suspicious_plot_as_living=0
- suspicious_immmo_only=0
- unverified_canonical_living=0
- unverified_immmo_only=0

UI must display ambiguous single-source card area as neutral `Fläche`, never as Wohnfläche.

## Property image policy

Do not invent or web-search an image by title. A catalog image must be tied to the exact source listing.

The father-facing catalog reads the first source-backed payload field among:
- `primary_image_url`
- `image_url`
- `thumbnail_url`

If none exists, the card shows a placeholder.

s REAL detail enrichment now extracts a source-backed main image from `og:image`, `twitter:image`/`twitter:image:src` or `rel=image_src` and persists it as `raw_payload.primary_image_url`.

To avoid aggressive source traffic:
- hourly/incremental s REAL runs do **not** fetch all detail pages
- full s REAL reconciliation adds `--enrich-details`
- this keeps exact metadata/images fresh roughly daily on the small s REAL corpus

IMMMO image extraction is not enabled yet. Do not destabilize the validated IMMMO parser merely for cosmetic coverage; add it only with a deterministic card-to-image association and regression tests.

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

Scheduler runs every 15 minutes and decides source due-ness from DB state. Successful job acquisition triggers location/concept post-processing.

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
- PostGIS geography provides scalable Luftlinie inclusion/prefilter
- local OSRM Table API adds fastest-driving distance/time
- same-PLZ/same-centroid pairs can legitimately report 0 km / 0 min

Latest post-repair road audit:
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

## Father-facing UX — CURRENT TARGET

The old `Kombinationen` page is no longer the primary product model. It may remain available as a legacy/debug surface.

Normal navigation is:
- **Häuser**
- **Stellen**

Root `/` redirects to `/houses`.

### `/houses`

Independent active-property catalog, 36 cards/page.

Filters:
- `ort`: city or postal code
- price min/max
- verified Wohnfläche min/max
- explicit Grundstück min/max

Cards show:
- source-backed image when available, otherwise placeholder
- location
- title
- price
- verified Wohnfläche, otherwise neutral source `Fläche` when available
- explicit Grundstück where semantically safe

### `/houses/{property_id}`

Full active-property detail page:
- image/placeholder
- title/location/price/areas
- source links
- description if stored
- radius selector, default 50 km
- all eligible geolocated jobs within the selected radius
- intrinsic fit score and salary/source data
- OSRM road distance/time when available

Radius inclusion is currently Luftlinie between resolved PLZ/locality centroids. This is deliberate and scalable. Road time is supplementary and must not be misrepresented as street-address precision.

### `/jobs`

Existing ranked job list remains the main job catalog:
- fit filters
- search
- favorite/hide curation
- eligible jobs link to their detail page

### `/jobs/{job_id}`

Full eligible-job detail page:
- job fit/salary/location/source links
- radius selector, default 50 km
- all active geolocated houses inside the selected Luftlinie radius
- 40 houses/page
- only the current page is road-refined through OSRM

This avoids giant all-to-all routing matrices while still giving useful travel information.

### Technical/admin surfaces

Keep protected legacy/admin tools available:
- `/admin/concepts`
- `/admin/jobs`
- `/admin/matches`
- `/matches` may remain as legacy/debug combinations view

Basic auth remains shared for now.

## New house-first implementation

Main code:
- `app/catalog.py`
- `app/templates/houses.html`
- `app/templates/house_detail.html`
- `app/templates/job_detail.html`

Existing `app/templates/admin_jobs.html` is reused for `/jobs`, now with house-first navigation and links to `/jobs/{id}`.

Tests cover:
- father-facing route registration/root redirect
- job curation redirect behavior
- source-backed image/neutral-area presentation
- duplicate ambiguous Fläche/Grund suppression
- PostGIS `ST_DWithin` + nearest-location radius query
- s REAL main-image extraction
- reconciliation-only s REAL detail enrichment command

## Immediate production steps after current CI is green

1. Pull branch on production and run Ruff/compile/tests. No migration required.
2. Restart `wohnwerk.service` and verify `/health`.
3. Verify `/` redirects to `/houses` and `/houses` + `/jobs` are Basic-auth protected.
4. Open `/houses` in browser and exercise filters/pagination.
5. Open one house and verify nearby jobs/radius semantics.
6. Open one eligible job and verify paginated nearby houses + current-page road refinement.
7. Run one controlled s REAL `--reconcile --enrich-details` with refresh timer paused to immediately backfill available source-backed images.
8. Count/list payloads with `primary_image_url` and visually verify several cards.
9. Restore refresh timer.
10. Only then consider deterministic IMMMO card-image extraction to raise image coverage beyond the s REAL subset.
