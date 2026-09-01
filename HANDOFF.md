# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-09-01 (Europe/Vienna)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This is the authoritative recovery point for a fresh context. Dynamic catalog counts are observations, not permanent invariants.

## Release state

- Current production: **v0.3.41**.
- Production SHA: `49db7ac20102f34ea6045668fa3deebc14e67bd6`.
- Current branch release candidate: **v0.3.42** — repair IMMMO reconciliation authority by separating structural coverage from synthetic-identity churn.
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

## IMMMO warning diagnosis and v0.3.42 policy

Production v0.3.41 currently reports IMMMO source coverage degraded because recent reconciliations are failing only the old synthetic-link-share gate.

Evidence from reconciliation #654:
- run success, 9/9 shards, 0 failed, traversal complete everywhere
- cards parsed == cards seen everywhere
- count delta = 0 within tolerance everywhere
- six shards fail only `synthetic > synthetic_tolerance`
- 1321 synthetic cards across 580 pages
- only **3 synthetic identities were new in the run**
- live audit of 24 high-synthetic pages found 182 current parser gaps; 179/182 had no current-card external link at all
- no useful non-`<a>` data/onclick links were found
- only 3/182 had a safe following title-prefix `<a>` parser miss

Conclusion: IMMMO legitimately publishes many source-less cards. Total synthetic share is not a source-coverage invariant. The old static 5/8% link-quality threshold conflates source behavior with parser failure.

v0.3.42 introduces coverage policy `immmo-identity-churn-2026-09-01-v1` in `app/crawling/immmo_quality.py`:
- structural authority requires reconciliation + traversal complete + no cap + cards_seen==cards_parsed + count delta in tolerance
- after ingest, each shard counts genuinely **new synthetic identities**
- identity churn fails closed if new synthetic rows exceed `max(3, 1% of cards seen)`
- legacy total-synthetic link-quality remains diagnostic only
- a stable population of source-less cards can therefore be authoritative
- a parser regression that suddenly converts many stable external URLs into new synthetic identities still degrades coverage

`audit_immmo_run.py` now prints structural state, synthetic-new count/tolerance, identity churn and policy version.

Do not manually change `Source.coverage_status`. After v0.3.42 deployment, prove the policy with a real reconciliation; only a resulting `coverage=ok` should clear the source warning and become disappearance-authoritative.

## Source health semantics

Execution success and coverage authority are independent:
- complete successful authoritative scan -> `success / ok`
- successful bounded incremental -> successful execution, non-authoritative coverage
- mixed actual failures -> `partial / degraded`
- all failed -> `failed / failed`

Only `coverage=ok` reconciliation may prove disappearance.

## Real-time UI synchronization TODO

Preferred direction remains SSE: server->browser invalidation/update events, current POSTs stay authoritative, reconnect/event IDs/keepalive, avoid aggressive polling. WebSockets only if a genuine bidirectional low-latency need appears.

## Current near-term roadmap

1. Production-gate v0.3.42 IMMMO identity-churn coverage policy and prove with one real reconciliation.
2. If reconciliation is `ok`, confirm admin warning clears and inspect disappeared/continuity effects before declaring IMMMO closed.
3. Do not extend geo cleanup further unless product impact warrants it.
4. Implement SSE dynamic website synchronization.
5. Continue product/matching/property work; do not resume generic job-source expansion.

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
