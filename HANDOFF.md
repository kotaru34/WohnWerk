# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-30 (Europe/Vienna)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This is the authoritative recovery point for a fresh context.

## Current release state

- Production is verified through **v0.3.27**.
- Production exact HEAD: `822cac80d0f1bf6daed71f752690048c662be766`.
- Current branch target is **v0.3.28**, adding a disabled-by-default PALFINGER direct-career source for live zero-write validation.
- Current discovery gate: `profile-seed-2026-08-30-v22`.
- Current salary text policy: `explicit-salary-text-2026-08-30-v6`.
- Father-facing relevant job catalog was 221 jobs after TGW promotion; later salary-only repairs do not change corpus membership.
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
- image/detail and liveness maintenance timers enabled
- `/health` is lightweight and unauthenticated
- father-facing `/houses`, `/jobs`, `/houses/{id}`, `/jobs/{id}` use HTTP Basic through `AdminDependency`
- do not use `/jobs/{id}` as automated smoke tests: the detail route calls `mark_job_viewed()`

Server timezone is `Europe/Vienna`; NTP remains enabled.

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

v22 includes TGW-driven corrections:
- title-level Sales rejection
- sales-oriented Application Engineer rejection
- technician / Installation Specialist structural rejection
- pure Controls/EPLAN structural rejection before generic engineering recall
- `mechanics` and `mechatronics` as domain evidence
- generic Project Manager accepted only with real mechanical/mechatronics product-development + PM evidence
- `after-sales service` is not confused with Sales/Vertrieb

Candidate fit policy remains independent (`candidate-fit-2026-08-28-v3`). Discovery decides whether a job belongs in the professional neighborhood; fit ranks accepted jobs.

## Enabled job sources

Operational/enabled:
- `karriere.at` — bounded discovery frontier
- `jobs.at` — bounded discovery frontier
- `stepstone.at` — bounded discovery frontier
- `willhaben-jobs` — bounded discovery frontier
- `lever-public-postings` — only TSMG retained after pruning
- `personio-public-xml`
- `smartrecruiters-public-postings`
- `workday-public-cxs` — KION + Magna discovery-frontier tenants
- `greenhouse-public-job-board` — validated zero-current-value watcher
- `successfactors-public-career-site` — ANDRITZ Professionals
- `tgw-direct-careers` — TGW Logistics

Disabled/candidate:
- `palfinger-direct-careers` — v0.3.28 candidate; must remain disabled until clean live preflight + corpus review + controlled import
- `immoads.at`

## Lever

v0.3.19 pruning retained only `global:tsmg`; Blackshark, Westernacher, cargo-partner and Qualysoft were disabled after zero useful live yield. TSMG remains the only useful current Lever tenant.

## Greenhouse

Enabled only as a validated zero-current-value watcher. gropyus, planetlabs, bitpanda and ketryx currently yield zero accepted under the current gate. Keep future postings only if they pass the current gate.

## Workday

KION + Magna are enabled discovery-frontier tenants. Workday search-text shards have no disappearance authority. Multi-shard tenant verification and source-reported-count normalization were fixed in v0.3.16.

## ANDRITZ / SuccessFactors

Generic public SuccessFactors adapter is production-enabled with ANDRITZ Professionals.

First validated import:
- source-reported global corpus ~487
- Austrian candidates 56
- accepted 19 at promotion, later current accepted count 18 after gate/lifecycle evolution
- all 19 initial accepted jobs were exclusive at promotion
- coverage `ok`
- imported locations resolved

Gate calibration from ANDRITZ added:
- industrial rotating-equipment/project variants
- embedded-hardware exclusion
- commercial-project-manager exclusion

Production salary repairs:
- NDT Quality Engineer: `4354.45 EUR/month`, minimum-only, no invented 14× annualization
- Projekt Manager Turbo Generatoren Service: `3583.02 EUR/month`, minimum-only, no invented 14× annualization

The Turbo Generator salary exposed SuccessFactors HTML text fragmentation (`M onat`); v0.3.27 salary policy v6 tolerates narrow whitespace fragmentation in explicit period tokens without globally concatenating arbitrary words.

## TGW direct careers

Production promotion succeeded in v0.3.25:
- run #333 reconciliation
- source reported 111 public jobs
- 58 Austrian candidates
- 8 accepted
- all 8 exclusive at promotion
- coverage `ok`
- all 8 locations resolved (Wels / Marchtrenk)

Accepted promotion corpus:
1. Mechatronics Development Manager - Rovosphere (M/F/D)
2. Project Manager (M/F/D)
3. Development Engineer for Mechatronic Systems (M/F/D)
4. Strategic (Senior) Project Manager – Mechatronics Product Development (M/F/D)
5. Project Manager - Mechatronic Product Development (M/F/D)
6. Mechatronics Development Engineer specialising in product maintenance (M/F/D)
7. Onsite Manager (M/F/D)
8. Overall Project Manager for New Installations (M/F/D)

`Technical Support Engineer Mechanics` was deliberately rejected after live review because it is support/dispatch/ticket + technician coordination rather than engineering/project leadership.

TGW salary repair:
- Strategic (Senior) Project Manager page explicitly states `64830 EUR/year`
- v0.3.26 extracts the salary separately because the normal TGW description intentionally stops before the benefits/salary block
- persisted annual minimum is exactly 64830; no inferred semantics required

## Salary parsing policy

Current policy: `explicit-salary-text-2026-08-30-v6`.

Invariants:
- preserve source pay period
- monthly Austrian salary is not automatically multiplied by 14
- monthly values annualize only when source explicitly gives payment count
- hourly values remain missing-last in annual salary sorting without defensible hours/week evidence
- structured source salary wins over text-derived salary
- generic text-derived salary needs explicit EUR currency, explicit pay period, plausible amount and salary cue
- trusted adapter-provided salary text may skip the generic cue but still needs explicit currency/period/plausibility

Supported live formats now include:
- Austrian/German grouping: `4.673,74`, `53 241,02`
- English grouping: `4,354.45`
- currency spellings: `€`, `EUR`, `Euro`
- narrow fragmented explicit period tokens such as `/ M onat`

Do not normalize arbitrary whitespace globally; fragmentation tolerance is deliberately narrow to avoid false positives.

## v0.3.28 PALFINGER candidate

PALFINGER is the next direct-employer acquisition target because its Austrian public career site has strong immediate mechanical/project value, including live roles such as:
- `Experienced Mechanical Engineer (f/m/d)` — cranes/system solutions, mechanical pre-development, FEM, prototypes/series, development-project leadership
- `Advanced Mechanical Engineer (w/m/d)`
- `Projekt Manager - Special Lifting Solutions (m/w/d)` — complex product/customer development projects, special lifting/robotics/rail applications
- industrial/plant engineering roles

PALFINGER Austrian business domain is highly relevant: hydraulic lifting/loading systems, cranes, railway systems, access platforms and related machinery.

v0.3.28 code adds:
- `app.sources.job.palfinger.PalfingerJobSource`
- `scripts/run_palfinger_jobs.py`
- disabled-by-default source seed `palfinger-direct-careers`
- scheduler registration while disabled (disabled rows remain ignored)
- public Austrian listing pagination parser
- direct detail parser with stable ID from PALFINGER posting id
- source-backed Austrian postal/city extraction from detail-page address
- source-backed salary text reuse through existing salary policy
- zero-write `--preflight`

Safety requirements before enablement:
1. live preflight must show real pagination evidence and full listing-page coverage
2. no detail parser failures
3. source remains disabled and DB unchanged during preflight
4. review every accepted title and important rejected families under gate v22
5. only then perform a hidden authoritative reconciliation, corpus/geo/salary audit, and enable source

The adapter deliberately marks coverage incomplete if pagination cannot be proven or a listing page/detail parser fails. Never enable PALFINGER merely because page 1 works.

## AVL follow-up candidate

AVL uses a SuccessFactors-style public career site and is cheap to add later as another tenant. Current Austrian feed, however, is relatively low-value at this exact moment (many Sales/IT/Marketing/Junior roles), so PALFINGER has priority for immediate exclusive value.

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
- Salzburg-area, Oberösterreich Zentralraum, Niederranna, St. Valentin, Salzburg Stadt/Vienna district and conservative `X bei Y` repairs are implemented

Known broad labels may remain unresolved when source evidence is insufficient.

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

1. Live zero-write PALFINGER preflight and full accepted/rejected review.
2. If PALFINGER is clean, controlled authoritative import + geo/salary/source-value audit + enablement.
3. Add AVL cheaply through the SuccessFactors framework if live value justifies it.
4. Continue selected Austrian direct employers based on exclusive value, not raw count.
5. Conservative geo cleanup only from real evidence.
6. Implement SSE real-time UI synchronization.

## Deployment discipline

For every branch change:
1. inspect final diff
2. wait for GitHub CI on the exact branch HEAD
3. require Install + Ruff + Compile + Tests success
4. only then provide production deployment commands
5. production still runs Ruff/compile/tests before restart
6. verify `/health` and targeted production data controls

Never deploy a red or intermediate SHA.
