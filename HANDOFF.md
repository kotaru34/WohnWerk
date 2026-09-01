# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-09-01 (Europe/Vienna)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This is the authoritative recovery point for a fresh context. Dynamic catalog counts are observations, not permanent invariants.

## Release state

- Current production: **v0.3.45**.
- Production SHA: `1b97f5e16d5e6e196237c2046f577a43cf1966cd`.
- Production DB migration: `0011_live_ui_events` (head).
- Current branch release candidate: **v0.3.46** — remaining evidence-backed job geography cleanup.
- Current concept extractor: `concept-seed-2026-09-01-v5`.
- Current discovery gate: `profile-seed-2026-08-30-v25`.
- Current salary policy: `explicit-salary-text-2026-08-30-v7`.
- Candidate fit policy: `candidate-fit-2026-08-28-v3`.
- Exact-head GitHub CI is a hard deployment gate. Never deploy temporary development commits.

`/health` exposes application version and `job_concept_extractor`. Mutating refresh work fails closed when disk and running web release/extractor differ.

## Product invariants

WohnWerk is a private/self-hosted Austria-first property + job acquisition, personalization and matching system for the candidate/father.

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

## House radius

v0.3.39 repaired the active `/houses` route after the v0.3.38 radius regression. Production proof: `/houses` 200 and Salzburg exact 1 -> Salzburg 50 km 37. Saved `radius_km` is 1..250 km, uses stored Austrian postal/locality centroids and PostGIS `ST_DWithin`; unresolved centers fail closed.

## Job geography

v0.3.41 repaired 11 concrete unresolved location rows without inventing points. Broad regions remain intentionally non-point.

A read-only production audit on v0.3.45 (`crawl_runs` stayed 691) established the remaining concrete cases:

- job #138 / SPIEGLTEC has five source locations: Innsbruck, Wien, Kundl, Brixlegg and **Schaftenau**. The first four are already resolved; only Schaftenau is missing. karriere.at employer/location evidence maps the Schaftenau site to postal code **6336 Langkampfen**. This is a real worksite, not a duplicate to discard.
- job #352 / teampool has source-backed `Graz, 8055` plus `Puntigam`; the job description explicitly says `Standort Graz-Puntigam`. Public Graz/ÖBB evidence confirms Puntigam in **8055 Graz**. Preserve the source label while using the verified 8055 centroid.
- job #160 / Lam Research already has a correct resolved Salzburg location plus an unresolved non-remote `city=AT, location_text='AT, Österreich'`. The latter is a country-code parser artifact, not a second worksite.

v0.3.46 release-candidate policy:
- add a tiny **verified sublocality** postal-membership table, separate from the Statistics-Austria municipality fallback
- `Schaftenau -> 6336`
- `Puntigam -> 8055`
- method: `verified_sublocality_postal_centroid`
- source metadata: `verified Austrian sublocality postal membership + BEV postal centroids`
- only the postal membership is curated; the actual point still comes exclusively from the locally imported BEV-backed postal centroid table
- no fuzzy matching and no region/country centre
- add postprocess cleanup for country-code city artifacts such as `AT`, but only when the row is non-remote, has no PLZ/point, and the same canonical job already has another concrete PLZ/point sibling
- countrywide remote scopes survive
- an `AT` row that is the only location evidence also survives rather than being silently discarded
- scheduled refresh publishes its job SSE invalidation only after this postprocessing, so father-facing UI never receives the transient artifact as the final refreshed state

Broad/non-point labels such as `Kärnten`, `Wels-Land`, `Bezirk Wels-Land` and `Graz Umgebung-West` must remain unresolved.

Development CI for v0.3.46 before squash: Ruff/Compile clean, **538 tests passed**. Added tests cover exact Schaftenau/Puntigam postal membership and fail-closed country-code cleanup semantics.

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

Manual production verification by the user: `Ausblenden` now works correctly without reload/navigation and without the page jumping upward.

## Current near-term roadmap

1. Squash v0.3.46 development commits into one atomic commit whose parent is exact production v0.3.45 SHA `1b97f5e...`.
2. Require exact-head GitHub CI: Install + Ruff + Compile + Tests all green.
3. Deploy v0.3.46 with timers quiesced; no DB migration required.
4. Run `scripts/resolve_job_locations.py` exactly once as the targeted repair/postprocess.
5. Production proof must show:
   - Schaftenau resolved by `verified_sublocality_postal_centroid` to the local 6336 centroid
   - Puntigam resolved by the same method to the local 8055 centroid
   - redundant non-remote `AT` row on job #160 removed while Salzburg remains
   - broad region rows remain unresolved
   - no crawl run is created by the repair
6. Restore exactly the timers active before deployment.
7. Close geo cleanup and move to matching/commute product work; do not resume generic job-source expansion.

## Deployment discipline

For every branch change:
1. inspect final diff
2. wait for GitHub CI on exact branch HEAD
3. require Install + Ruff + Compile + Tests success
4. squash development commits into one atomic release commit over current production
5. wait for exact-head CI on that atomic release SHA
6. only then deploy
7. production reruns Ruff/compile/tests before restart
8. verify `/health` plus targeted production controls
9. never deploy a red/intermediate SHA
