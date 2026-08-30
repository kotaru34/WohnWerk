# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-30 (Europe/Vienna)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This is the authoritative recovery point for a fresh context.

## Current release state

- Production is verified through **v0.3.25**.
- Current branch target is **v0.3.26**, a source-backed salary parsing repair for TGW + ANDRITZ.
- Production v0.3.25 exact HEAD: `6dbe48aadf03f75e6a099b1020559411b565be96`.
- Current discovery gate: `profile-seed-2026-08-30-v22`.
- Father-facing relevant job catalog after TGW promotion: **221 jobs**.
- Exact-head GitHub CI success is a hard production deployment gate.

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

## Runtime

Public URL: `https://wohnwerk.kotaru.lainlounge.org`

- Caddy -> `127.0.0.1:8000`
- FastAPI/Uvicorn service: `wohnwerk.service`
- local OSRM: `127.0.0.1:5000`
- refresh scheduler timer: 15-minute wake-up
- image/detail and liveness maintenance timers remain enabled
- `/health` is lightweight and unauthenticated
- father-facing `/houses`, `/jobs`, `/houses/{id}`, `/jobs/{id}` are HTTP-Basic protected through `AdminDependency`
- do not use job detail URLs as automated smoke tests: `/jobs/{id}` calls `mark_job_viewed()`

## Candidate / father profile

Profile slug: `mechanical-project-engineer`  
UI label: `Maschinenbau / technische Projektleitung`

Approx. 30 years in mechanical engineering and technical project leadership, including:
- product development and mechanical design
- machinery, automotive/special vehicles, rail vehicles, fixtures/special machinery
- technical project management and team leadership
- supplier coordination
- Lasten-/Pflichtenhefte and schedule ownership
- testing, assembly and commissioning context
- FEM, FMEA
- classic and agile project work

Strong target neighborhood: senior mechanical engineering, development engineering, technical project/program leadership and engineering leadership.

Structural/near-structural exclusions:
- Sales / Vertrieb
- software/IT development and coding
- pure electrical engineering
- construction / building services / TGA / HKLS
- technician / trade / Facharbeiter / Monteur roles
- junior / graduate / trainee roles
- commercial / kaufmännisch project roles
- procurement / Einkauf
- HR

Discovery is intentionally broader than final fit, but obvious structural non-targets must be rejected before persistence.

## Discovery and fit

Current discovery gate: **v22** (`profile-seed-2026-08-30-v22`).

v22 includes the TGW-driven corrections:
- title-level Sales rejection
- sales-oriented Application Engineer rejection
- technician / Installation Specialist structural rejection
- pure Controls/EPLAN structural rejection before generic engineering recall
- `mechanics` and `mechatronics` as domain evidence
- generic Project Manager accepted only with real mechanical/mechatronics product-development + PM evidence
- `after-sales service` is not confused with Sales/Vertrieb

Candidate fit policy remains independent (`candidate-fit-2026-08-28-v3`). Context evidence may lower/raise ranking without redefining job identity. Primary incompatible role/domain evidence can hard-cap a fit.

## Job sources

Enabled/operational:
- `karriere.at` — bounded discovery frontier
- `jobs.at` — bounded discovery frontier
- `stepstone.at` — bounded discovery frontier
- `willhaben-jobs` — bounded discovery frontier
- `lever-public-postings` — only TSMG remains enabled after pruning
- `personio-public-xml`
- `smartrecruiters-public-postings`
- `workday-public-cxs` — KION + Magna discovery-frontier tenants
- `greenhouse-public-job-board` — enabled as validated zero-current-value watcher
- `successfactors-public-career-site` — ANDRITZ Professionals
- `tgw-direct-careers` — TGW Logistics

Disabled:
- `immoads.at`

### Lever

v0.3.19 pruning retained only `global:tsmg`; Blackshark, Westernacher, cargo-partner and Qualysoft were disabled after live accepted yield 0. TSMG was the only useful current tenant.

### Greenhouse

Enabled after a clean authoritative zero-value validation: gropyus, planetlabs, bitpanda and ketryx all currently yield zero accepted under the current gate. Keep as a future watcher; do not inflate corpus with rejected rows.

### Workday

KION + Magna are enabled discovery-frontier tenants. Workday search-text shards have no disappearance authority. Multi-shard tenant verification and source-reported-count normalization were fixed in v0.3.16.

### ANDRITZ / SuccessFactors

Generic public SuccessFactors adapter is production-enabled with ANDRITZ Professionals.

Validated first import:
- source-reported global corpus ~487
- Austrian candidates 56
- accepted 19
- all 19 exclusive at promotion time
- coverage `ok`
- all imported locations resolved

Gate calibration from ANDRITZ added industrial rotating-equipment/project variants, embedded-hardware exclusion and commercial-project-manager exclusion.

### TGW direct careers

`v0.3.25` production promotion succeeded:
- run #333 reconciliation
- source reported 111 public jobs
- 58 Austrian candidates
- 8 accepted
- all 8 exclusive at promotion time
- coverage `ok`
- all 8 locations resolved (Wels / Marchtrenk)
- father-facing authenticated list smoke test rendered all 8 without visiting detail routes

Accepted TGW corpus at promotion:
1. Mechatronics Development Manager - Rovosphere (M/F/D)
2. Project Manager (M/F/D)
3. Development Engineer for Mechatronic Systems (M/F/D)
4. Strategic (Senior) Project Manager – Mechatronics Product Development (M/F/D)
5. Project Manager - Mechatronic Product Development (M/F/D)
6. Mechatronics Development Engineer specialising in product maintenance (M/F/D)
7. Onsite Manager (M/F/D)
8. Overall Project Manager for New Installations (M/F/D)

`Technical Support Engineer Mechanics` was deliberately rejected after live review: support/dispatch/ticket + technician coordination with apprenticeship/HTL profile, not engineering/project leadership.

## v0.3.26 salary repair

Two live employer-owned pages exposed salary parsing gaps:

1. TGW Strategic (Senior) Project Manager page states an explicit minimum annual salary as `64.830 Euro`.
   - TGW description intentionally stops before benefits/salary, so salary must be captured separately as source-backed `salary_text`.
   - Do not broaden the normal description just to reach the salary paragraph.

2. ANDRITZ Quality Engineer NDT page states `€4,354.45 gross per month`.
   - SuccessFactors description already contains the salary paragraph.
   - Generic money parsing previously supported Austrian/German grouping such as `4.673,74` but not English grouping `4,354.45`.

v0.3.26 changes:
- generic salary parser accepts English grouped amounts (`4,354.45`) in addition to existing Austrian/German forms
- written currency `Euro` is accepted alongside `EUR` and `€`
- generic description parsing still requires salary cue + explicit period + plausible amount
- TGW adapter extracts an explicit salary block separately into `RawJob.salary_text`
- salary text policy bumped to `explicit-salary-text-2026-08-30-v5`
- regression tests cover the exact TGW and ANDRITZ live formats plus a non-salary `Euro` budget false-positive guard

Expected semantics after repair:
- TGW: minimum `64830 EUR/year`, minimum-only
- ANDRITZ NDT: minimum `4354.45 EUR/month`, minimum-only
- ANDRITZ monthly salary is **not** annualized because the posting does not explicitly state 14 payments; do not invent 14× semantics

The generic job runner calls salary-text enrichment before discovery partition/ingestion, so a successful authoritative reconciliation of TGW and SuccessFactors after v0.3.26 deployment repairs existing active jobs without a bespoke database migration.

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
- images are exact source-backed only
- conservative dedupe only; no invented semantics

IMMMO continuity v3 repair is complete/idempotent and should not be reopened without concrete evidence.

## Job geography

- explicit source PLZ wins
- otherwise conservative known-locality centroid
- broad Bundesland/country labels stay unresolved rather than receiving fake coordinates
- Salzburg-area, Oberösterreich Zentralraum, Niederranna, St. Valentin, Salzburg Stadt/Vienna district and conservative `X bei Y` repairs are already implemented

Known broad/unresolved labels may remain unresolved when source evidence is insufficient.

## Salary invariants

- Preserve source pay period.
- Monthly Austrian salary is not automatically multiplied by 14.
- Monthly values are annualized only when the source explicitly provides payment count.
- Hourly values remain missing-last in annual salary sorting unless explicit working-hours evidence exists.
- Structured source salary wins over text-derived salary.
- Text-derived salary requires explicit currency, explicit pay period and plausible value; generic descriptions additionally require a salary cue.

## Source health semantics

Execution success and coverage authority are separate:
- complete successful authoritative scan -> `success / ok`
- successful bounded frontier -> `success / degraded`
- mixed actual failures -> `partial / degraded`
- all failed -> `failed / failed`

Only `coverage=ok` reconciliation may prove disappearance.

## Operations / source value

`/admin/health` tracks execution/coverage plus source value:
- active accepted listings
- catalog jobs
- exclusive/shared jobs
- latest candidate/accepted/rejected counts
- gate yield

Use exclusive useful coverage to decide whether a source deserves ongoing maintenance.

## Real-time UI synchronization TODO

Preferred approach remains SSE:
- server -> browser invalidation/update
- existing POSTs remain authoritative for writes
- reconcile affected cards/counters without full reload
- event IDs, reconnect and keepalive
- no aggressive polling
- WebSockets only if genuine bidirectional low-latency needs arise

## Near-term roadmap

1. Deploy/verify v0.3.26 salary repair and reconcile TGW + ANDRITZ so existing jobs gain source-backed salary data.
2. Continue selected direct Austrian employer acquisition where exclusive value is likely.
3. Keep tuning tenant/source value rather than expanding for raw count.
4. Conservative geo cleanup only from real evidence.
5. Implement SSE real-time UI synchronization.

## Deployment discipline

For every branch change:
1. inspect final diff
2. wait for GitHub CI on the exact branch HEAD
3. require Install + Ruff + Compile + Tests success
4. only then provide production deployment commands
5. production still runs Ruff/compile/tests before restart
6. verify `/health` and targeted production data controls

Never deploy a red or intermediate SHA.
