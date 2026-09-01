# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-09-01 (Europe/Vienna)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This is the authoritative recovery point for a fresh context. Dynamic catalog counts are observations, not permanent invariants.

## Release state

- Current production: **v0.3.44**.
- Production SHA: `c2d4965c7d4b7cdae5beb19abb4f399fc4cbcbf2`.
- Production DB migration: `0011_live_ui_events` (head).
- Current branch release candidate: **v0.3.45** — no-navigation curation UX and scroll-preserving live refresh.
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

v0.3.41 repaired 11 concrete unresolved location rows without inventing points. Father-visible unresolved fell from 18 to 7. Broad regions remain intentionally non-point.

Known remaining geo work includes broad/non-point labels such as `Kärnten`, `Wels-Land`, `Bezirk Wels-Land`, `Graz Umgebung-West`, plus later candidates `Schaftenau`, `Puntigam`, and source-parser case `AT` on jobs.at. Do not map broad areas to arbitrary centroids.

## IMMMO coverage authority

v0.3.42 is deployed in production history and remains the active IMMMO coverage policy. It repaired IMMMO reconciliation authority by separating structural source coverage from stable synthetic/source-less identity share.

Coverage policy: `immmo-identity-churn-2026-09-01-v1` in `app/crawling/immmo_quality.py`:
- structural authority requires reconciliation + traversal complete + no cap + cards_seen==cards_parsed + count delta in tolerance
- after ingest, each shard counts genuinely **new synthetic identities**
- identity churn fails closed if new synthetic rows exceed `max(3, 1% of cards seen)`
- legacy total-synthetic link-quality remains diagnostic only
- a stable population of source-less cards can therefore be authoritative
- a parser regression that suddenly converts many stable external URLs into new synthetic identities still degrades coverage

Evidence that motivated the policy: reconciliation #654 completed 9/9 shards with cards parsed == cards seen and source-count deltas in tolerance; 1321 source-less/synthetic cards existed across 580 pages but only 3 synthetic identities were genuinely new in the run. A live audit found most apparent link gaps were source cards with no current external link rather than parser misses.

Do not manually change `Source.coverage_status`. Only the result of a real complete reconciliation controls disappearance authority.

## Source health semantics

Execution success and coverage authority are independent:
- complete successful authoritative scan -> `success / ok`
- successful bounded incremental -> successful execution, non-authoritative coverage
- mixed actual failures -> `partial / degraded`
- all failed -> `failed / failed`

Only `coverage=ok` reconciliation may prove disappearance.

## SSE/live synchronization

v0.3.43 introduced server-sent invalidation events while keeping existing server-rendered pages and POST write paths authoritative. v0.3.44 fixed isolated-process SQLAlchemy model registration for durable event writes.

Production-proven architecture:
- durable `live_ui_events` journal in Postgres via Alembic revision `0011_live_ui_events`
- authenticated `GET /events` SSE endpoint
- monotonic event IDs and `Last-Event-ID`/query-cursor replay across reconnects and web-process restarts
- 15-second keepalive; DB polling is bounded and uses short sessions
- no Redis and no in-memory-only broker, because crawler and web processes are separate
- events have `houses`, `jobs` or `all` topic plus kind/entity/profile/payload metadata
- favorite/hidden/viewed events are queued in the same DB transaction as their authoritative state change
- property crawler emits one `houses/catalog_refresh` after the completed run
- job source runners deliberately do **not** emit intermediate catalog events
- `scripts/refresh_sources.py` emits one `jobs/catalog_refresh` only after all successful job-source runs have completed location resolution, location propagation and concept normalization
- if any job postprocess fails, no job invalidation is published

v0.3.44 production proof:
- server release gate passed with 530 tests
- isolated `LiveUiEvent.profile_id -> candidate_profiles.id` FK registration passed
- controlled durable `deployment_probe` insert succeeded
- `/houses` and `/jobs` publicly rendered the live client
- unauthenticated `/events` returned 401
- authenticated SSE `ready` + replay of probe event succeeded through Caddy/TLS
- all refresh/images/liveness timers were restored active

## v0.3.45 curation UX fix

User-visible defect found after SSE deployment: clicking house `Ausblenden` still used the old browser form navigation path (`POST -> 303 -> /houses...`), causing a full navigation and scroll jump to the top. SSE itself did not remove that navigation.

v0.3.45 fixes the browser interaction layer without changing the authoritative backend write paths:
- shared live client delegates `submit` events for existing house/job `favorite` and `hidden` POST forms
- matched curation forms are sent with `fetch()` and `FormData`; `preventDefault()` stops browser navigation
- existing CSRF fields and backend POST handlers remain authoritative and unchanged
- submit buttons are disabled while the request is in flight to prevent duplicate writes
- after a successful write, the existing server-rendered current page is refreshed in-place
- before `<main>` replacement the client captures a visible `house-*`/`job-*` viewport anchor and `scrollY`
- after replacement the client restores the same visual anchor; if the anchor disappeared (for example the just-hidden card), it restores the previous scroll offset rather than jumping to the top
- SSE-triggered refresh uses the same viewport-preserving path, so crawler/cross-tab invalidations also should not jump the page
- progressive enhancement remains: without JS, legacy POST+303 still works
- deliberate exception: hiding a house while already on `/houses/{id}` keeps the navigation fallback, because that detail URL is intentionally no longer valid after the house is hidden

The interception automatically covers catalog house actions, catalog job actions and house curation inside job-detail pages by matching the existing action URL shape; no template contract changes are required.

Development CI for v0.3.45: Ruff/Compile clean and 533 tests passed. Added regression assertions verify delegated submit interception, `preventDefault`, fetch/FormData submission, duplicate-submit guard, viewport snapshot/restore and the house-detail-hide navigation exception.

## Current near-term roadmap

1. Squash v0.3.45 development commits into one atomic commit whose parent is exact production v0.3.44 SHA `c2d4965...`.
2. Require exact-head GitHub CI: Install + Ruff + Compile + Tests all green.
3. Deploy v0.3.45 with the usual timer quiesce/server gate/restart procedure; no DB migration is required.
4. Production UX proof should be manual/browser-based: scroll well down `/houses`, click `Ausblenden`, verify no browser navigation/reload and no jump to page top; also test Favorit and one Stellen curation action.
5. Confirm public health and restore exactly the timers that were active before deploy.
6. Only after this UX regression is closed return to geo/matching backlog.

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
