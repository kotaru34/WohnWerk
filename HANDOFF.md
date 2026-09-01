# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-09-01 (Europe/Vienna)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This is the authoritative recovery point for a fresh context. Dynamic catalog counts are observations, not permanent invariants.

## Release state

- Current production: **v0.3.43**.
- Production SHA: `e133e330a3d3da84c7a58797318bb7c55b0a5d56`.
- Production DB migration: `0011_live_ui_events` (head).
- Current branch release candidate: **v0.3.44** — runtime model-registration hotfix for durable live-event writes.
- v0.3.43 web rendering, Basic Auth protection and live-client injection are healthy, but the final deployment probe exposed an isolated-process SQLAlchemy metadata bug before the first `live_ui_events` insert: `app.live_events` referenced `candidate_profiles` without registering `CandidateProfile`. Keep acquisition timers quiesced until v0.3.44 is deployed and the insert/replay probe passes.
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

## v0.3.43 live UI synchronization

v0.3.43 introduced server-sent invalidation events while keeping existing server-rendered pages and POST write paths authoritative.

Architecture:
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

Browser behavior:
- one shared client is injected into authenticated `/houses*` and `/jobs*` HTML
- SSE invalidation fetches the same current URL with `cache: no-store`
- only `<main>` is replaced; there is no page navigation/F5
- the live client itself remains outside `<main>` and survives DOM replacement
- multiple rapid invalidations are coalesced
- refresh is deferred while an input/select/textarea/contenteditable inside `<main>` has focus, then applied after editing ends
- current POST forms remain unchanged and authoritative
- unauthenticated product requests do not perform a live-event DB cursor read before Basic Auth

Production deployment of v0.3.43 succeeded through code/tests/migration/web startup: 529 tests passed, DB migrated `0010_property_activity -> 0011_live_ui_events`, `/houses` and `/jobs` rendered the live client, public `/health` reported v0.3.43, and unauthenticated `/events` returned 401. The first controlled durable insert then failed with `NoReferencedTableError` because isolated `app.live_events` import did not register `candidate_profiles` in SQLAlchemy metadata. The transaction rolled back, so no probe event was persisted.

## v0.3.44 runtime hotfix

The hotfix makes `app.live_events` explicitly import/register `CandidateProfile`, eliminating the runtime dependency on unrelated import order. `candidate_fit.py` does not import `live_events`, so this does not introduce a circular import.

Regression coverage deliberately removes the previous explicit `CandidateProfile` import from `tests/test_live_events.py` and verifies that `LiveUiEvent.profile_id` resolves its FK target from an isolated live-events import. Development CI after the fix: Ruff/Compile clean and 530 tests passed.

## Current near-term roadmap

1. Squash the v0.3.44 development commits into one atomic commit whose parent is exact deployed v0.3.43 SHA `e133e330...`.
2. Require exact-head GitHub CI: Install + Ruff + Compile + Tests all green.
3. Keep refresh/images/liveness timers quiesced during the hotfix deployment.
4. Fast-forward production to v0.3.44; migration remains `0011_live_ui_events` (no new DB schema change).
5. Rerun server Ruff/compile/tests and restart web.
6. Repeat the controlled `deployment_probe` insert, authenticated public SSE ready/replay test, `/houses` + `/jobs` live-client smoke, and public health check.
7. Only after successful durable insert/replay restore exactly the timers that were active before the incident.
8. Continue product/matching/property work; do not resume generic job-source expansion.

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
