# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-09-01 (Europe/Vienna)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This is the authoritative recovery point for a fresh context. Dynamic catalog counts are observations, not permanent invariants.

## Release state

- Production baseline before the current radius-filter rollout: **v0.3.37**.
- Production baseline SHA: `e9e9883565ab97e9ad6c375b4fd1a39e057f8622`.
- Current branch release candidate: **v0.3.38** — saved house locality + radius filtering.
- Current concept extractor: `concept-seed-2026-08-31-v4`.
- Current discovery gate: `profile-seed-2026-08-30-v25`.
- Current salary policy: `explicit-salary-text-2026-08-30-v7`.
- Candidate fit policy: `candidate-fit-2026-08-28-v3`.
- Exact-head GitHub CI is a hard deployment gate. Never deploy one of the temporary development commits used while building a release.

`/health` exposes both application version and `job_concept_extractor`. Since v0.3.37, mutating refresh work fails closed when the code on disk and the running web reader do not report the same release/extractor pair. This release-mismatch guard was proven on production in both negative and positive directions without database writes.

## Product invariants

WohnWerk is a private/self-hosted Austria-first property + job acquisition, personalization and matching system for the candidate/father.

- App/user UI is German-only.
- Father-facing product has independent **Häuser** and **Stellen** catalogs.
- Source lifecycle, discovery relevance and candidate fit are separate concerns.
- Failed/partial crawls never mass-deactivate authoritative data.
- Missing from a bounded frontier search is not disappearance proof.
- Disabled sources never contribute father-visible jobs.
- Hidden/favorite/viewed curation survives lifecycle/canonical merges.
- Never invent coordinates, images, prices, salary semantics or property attributes.
- Geography/commute remains separate from intrinsic job fit.
- No permanent Job×Property pair table unless future measurements justify it.
- Only a complete authoritative `coverage=ok` reconciliation may prove disappearance.

## Runtime

Public URL: `https://wohnwerk.kotaru.lainlounge.org`

- Caddy -> `127.0.0.1:8000`
- FastAPI/Uvicorn service: `wohnwerk.service`
- local OSRM: `127.0.0.1:5000`
- refresh scheduler: `wohnwerk-refresh.timer`
- image worker: `wohnwerk-images.timer`
- liveness worker: `wohnwerk-liveness.timer`
- `/health` is lightweight and unauthenticated
- father-facing `/houses`, `/jobs`, `/houses/{id}`, `/jobs/{id}` use HTTP Basic through `AdminDependency`
- do not use `/jobs/{id}` as an automated HTTP smoke test because the detail route marks the job viewed

Server timezone: `Europe/Vienna`.

## Candidate profile and matching

Profile slug: `mechanical-project-engineer`  
UI label: `Maschinenbau / technische Projektleitung`

Approx. 30 years in mechanical engineering and technical project leadership, including product development, mechanical design, machinery, vehicles/special vehicles, rail, special machinery/fixtures, technical project leadership, suppliers, requirements/specifications, schedules, testing/assembly/commissioning, FEM and FMEA.

Strong target neighborhood:
- senior mechanical engineering
- development engineering
- technical project/program leadership
- engineering leadership

Structural/near-structural exclusions include Sales/Vertrieb, software/IT development, pure electrical, construction/TGA/HKLS, technician/trade roles, junior/trainee roles, commercial PM, procurement and HR.

Discovery remains deliberately broader than candidate fit. Fit is recomputed live from persisted current-extractor concept evidence and persisted profile preferences; `Job.job_fit_score` is not the source of truth.

## Candidate preference state

Profile seed: `candidate-profile-2026-08-28-v2`.

Manual preferences override seed-managed preferences and survive future seed synchronization.

The two concepts introduced during PALFINGER calibration are manually rated by the father:
- `role:industrial-engineer = cannot_not_want`
- `role:quality-manager = cannot_not_want`

These primary role states intentionally make matching Industrial Engineer / Quality Manager postings hard-incompatible under fit policy v3.

## Job-source expansion phase: CLOSED

Do **not** continue adding job sources merely to increase raw source count. The acquisition phase is considered sufficiently broad. From this checkpoint onward, job-source work is maintenance/repair only unless a concrete coverage gap justifies reopening expansion.

Enabled job sources include:
- `karriere.at`
- `jobs.at`
- `stepstone.at`
- `willhaben-jobs`
- `lever-public-postings` (useful retained tenant: TSMG)
- `personio-public-xml`
- `smartrecruiters-public-postings`
- `workday-public-cxs`
- `greenhouse-public-job-board` (validated watcher)
- `successfactors-public-career-site`
- `tgw-direct-careers`
- `palfinger-direct-careers`

`immoads.at` remains disabled.

### PALFINGER final production promotion

PALFINGER is fully promoted and enabled. Do not rerun its reconciliation merely to re-prove the promotion.

Promotion proof:
- source id 15
- 7 active discovery-accepted persisted listings
- enable changed father-visible catalog by exactly +7, with no removals
- enable itself did not change crawl count or concept evidence corpus
- refresh timer restored afterward

Promoted jobs at enable time:
- 355 Experienced Mechanical Engineer — score 65, compatible
- 356 Industrial Engineer — score 25, hard incompatible via `role:industrial-engineer`
- 357 Arbeitstechniker / Industrial Engineer — score 25, hard incompatible via `role:industrial-engineer`
- 358 Plant Quality Manager — score 24, hard incompatible via `role:quality-manager`
- 359 Projekt Manager - Special Lifting Solutions — score 92, compatible
- 360 Entwicklungsingenieur Kransysteme oder Fahrzeugtechnik — score 79, compatible
- 361 Development Engineer - Service & Diagnostic Tools — score 70, compatible

Observed father-visible count immediately before/after promotion was 240 -> 247. This count may drift naturally as sources refresh; the exact +7 promotion delta is the invariant, not 247 forever.

## Job concept / salary policies

Concept extractor: `concept-seed-2026-08-31-v4`.

v4 added/expanded industrial engineering vocabulary without silently assigning father preferences, including:
- `role:industrial-engineer`
- `role:quality-manager`
- project manager alias coverage
- automotive/special-machinery/mechanical aliases
- product development, production/manufacturing, calculation/simulation, project management and technical documentation phrases

Salary policy: `explicit-salary-text-2026-08-30-v7`.

Important salary invariants:
- preserve source pay period
- no automatic Austrian monthly ×14 assumption
- monthly annualization only with explicit payment count
- hourly annualization remains missing-last without defensible hours/week evidence
- structured source salary wins text-derived salary
- text parsing requires explicit currency/period/plausibility and appropriate cue unless trusted source semantics provide the cue context
- narrow fragmented period forms are supported; arbitrary whitespace gluing is not
- explicit yearly wording is supported in v7

## Property sources and semantics

Authoritative property sources:
- `immmo.at`
- `sreal.at`

ImmoAds remains disabled.

Property rules:
- explicit Wohnfläche/Wohnnutzfläche -> living area
- explicit Grundstück/Grundstücksfläche/Grundfläche -> plot area
- explicit Nutzfläche -> usable area
- generic source area -> neutral display-only area
- source-backed images only
- conservative dedupe only
- never invent property coordinates or attributes

At this checkpoint the admin source page reports `immmo.at` as warning/degraded. This is an explicit pending diagnostic task; do not paper over it by changing the UI status without understanding the latest run/coverage evidence.

## House locality + radius release candidate (v0.3.38)

The current branch adds an optional saved `radius_km` house filter so a user can enter e.g. `Salzburg` + `50` and receive properties geographically within 50 km, not only rows whose city text contains Salzburg.

Design:
- existing exact/substring `Ort oder PLZ` behavior remains when radius is empty
- radius accepts 1..250 km and is meaningful only with a non-empty location
- filter persists in the existing house-filter cookie
- 4-digit PLZ uses the stored Austrian postal centroid
- locality names use the existing conservative Austrian job-locality resolver/reference corpus
- actual filtering uses PostGIS `ST_DWithin` on `Property.location`
- no external geocoder and no invented coordinates
- unresolved radius center fails closed to zero matches and displays a German explanation instead of silently reverting to textual city matching
- saved house radius filters also remain in force when viewing houses around a job

Before production rollout, v0.3.38 still requires final exact-head CI and standard production verification.

## Job geography

Existing policy:
- explicit source PLZ wins
- otherwise conservative known-locality centroid
- broad Bundesland/country labels stay unresolved instead of receiving fake point coordinates
- approximate area anchors are allowed only where an explicit conservative policy exists

Pending unresolved-location audit from the current product UI:
- Sankt Pölten
- AT
- Bezirk Wels-Land
- Blaindorf
- Ebenthal in Kärnten
- Graz Umgebung-West
- Kärnten
- Premstätten
- Puntigam
- Ranshofen
- Sankt Florian am Inn
- Schaftenau
- Traboch
- Wels-Land
- österreichweit

Do not automatically point-resolve country/state/district-wide labels such as `AT`, `österreichweit`, `Kärnten` or `Bezirk Wels-Land`. Audit actual source rows and postal/locality evidence first. Real localities/spelling variants should be fixed from evidence, not guessed.

## Source health semantics

Execution success and coverage authority are separate:
- complete successful authoritative scan -> `success / ok`
- successful bounded frontier -> successful execution with non-authoritative/unknown or degraded coverage as appropriate
- mixed actual failures -> `partial / degraded`
- all failed -> `failed / failed`

Only `coverage=ok` reconciliation may prove disappearance.

`/admin/health` tracks source execution/coverage and source value. Use useful/exclusive coverage rather than raw item count when deciding maintenance value.

## Real-time UI synchronization TODO

Preferred direction remains SSE:
- server -> browser invalidation/update events
- existing POSTs remain authoritative for writes
- reconcile affected cards/counters without forcing a full reload where practical
- event IDs, reconnect and keepalive
- avoid aggressive polling
- WebSockets only if a genuine bidirectional low-latency need appears

This is an active near-term task after geo/source-health cleanup.

## Current near-term roadmap

1. Finish and production-gate v0.3.38 house locality + radius filter.
2. Audit and repair real unresolved job localities; preserve broad scopes as intentionally non-point.
3. Diagnose `immmo.at` warning/degraded from actual crawl/coverage evidence.
4. Implement dynamic website data synchronization (SSE TODO).
5. Diagnose why job #374 receives no fit score and fix the underlying concept/evidence issue conservatively.
6. Continue remaining product/matching/property tasks; do not resume generic job-source expansion.

## Deployment discipline

For every branch change:
1. inspect final diff
2. wait for GitHub CI on the exact branch HEAD
3. require Install + Ruff + Compile + Tests success
4. only then provide production deployment commands
5. production reruns Ruff/compile/tests before restart
6. verify `/health` plus targeted production data controls
7. never deploy a red or intermediate SHA

When a release changes code on disk before the long-lived web service restarts, keep the refresh release-mismatch guard in mind; it must defer mutating source work until runtime and disk report matching release/extractor markers.
