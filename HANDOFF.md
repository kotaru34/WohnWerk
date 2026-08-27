# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-28 (Europe/Berlin)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This file is the authoritative recovery point for continuing WohnWerk in a fresh context.

## Product direction / invariants

WohnWerk is a private/self-hosted Austria-first house + job acquisition, personalization and matching system.

- End-user UI is German only.
- Never request or print DB passwords.
- `JobListing.status` is source lifecycle only.
- Professional-neighbourhood relevance is independent in `raw_payload["wohnwerk_discovery_gate"]`.
- Application liveness/freshness is independent from source lifecycle and relevance.
- Candidate fit/preferences are independent and recomputable.
- Gate/taxonomy changes must never masquerade as source disappearance.
- New rejected candidates are normally not durably persisted; previously persisted source-visible listings can remain active while locally irrelevant.
- Failed/partial reconciliation never mass-deactivates.
- Canonical jobs deactivate only when none of their source listings remains active.
- Do not invent Austrian PLZ/location points; approximate geography keeps provenance.
- Geography is separate from intrinsic job fit; use PostGIS rather than permanent NxM pairs.
- No CAPTCHA bypass, credential theft, fingerprint spoofing or deliberate anti-bot evasion.

## Stable property acquisition

Do not reopen absent a live regression:

- IMMMO #11: coverage OK, 13,948 seen, 1,167 pages, 9/9 shards, disappeared=0.
- s REAL #16: coverage OK, 314 seen, detail-enriched, disappeared=0.
- ImmoAds retired/disabled.

## Existing ATS job sources — stable supplementary layers

### SmartRecruiters

Correctness closed on production #33:

- 15/15 shards, coverage OK, source_reported=411.
- 53 source-active listings.
- 42 relevant-active canonical jobs.
- 41/42 relevant locations resolved.
- remaining Tirol regional scope intentionally non-point.

Liveness previously confirmed 43/43 relevant-active rows live. Republish identity is source-backed as `smartrecruiters:{tenant}:jobad:{jobAdId}`. Production repair backfilled 56 identities, merged two verified Anton Paar republish canonical duplicates and left zero duplicate identity groups.

### Personio

Correctness/calibration closed on production #37:

- DE + EN XML merged by stable Personio position ID.
- 14/14 shards, 28 requests/pages, coverage OK.
- source_reported=215 without language doubling.
- 17 relevant-active canonical jobs.
- only unresolved relevant location is `österreichweit`, intentionally non-point.
- stale `Center Vienna` cleanup and FEM/`female` evidence fix production-confirmed.

Keep Personio as a supplementary clean feed. Do not spend primary acquisition effort manually finding employers one by one.

### Lever

Production #22 remains stable:

- 5/5 shards, coverage OK.
- 6 relevant active jobs.
- all relevant locations resolved.

A registry-driven verifier exists, but manual Lever tenant expansion is no longer a primary scaling path.

## Discovery gate v14 — correctness closed for now

Current version: `profile-seed-2026-08-28-v14`.

v13 generic parity was production-confirmed for HKLS/building-services, technical field service and production management while structurally excluding KFZ workshop trades. v14 only corrects the FEM evidence boundary: `FEM`, `FEA` and `finite element(s)` match; EEO words such as `female` do not.

Do not micro-calibrate discovery unless a broad corpus exposes another genuinely generic correctness problem. Candidate preference never belongs in discovery.

## PRIMARY JOB ACQUISITION STRATEGY — broad Austrian job boards first

This is now the dominant architecture priority.

Operating model explicitly requested by the user:

- behave like a person quickly scanning titles;
- run a handful of focused title searches instead of crawling an entire marketplace;
- inspect only the first visible result page initially;
- deduplicate listing IDs before detail requests;
- open a detail page only when the title looks worth inspecting;
- serialize requests with a deliberate delay;
- keep online-service load low;
- only later add deeper traversal/enrichment when there is a concrete need.

Current board order:

1. karriere.at
2. jobs.at
3. AMS `alle jobs` / eJob-Room
4. willhaben Jobs
5. StepStone Austria

Broad-board rules:

- preserve stable source listing identity;
- preserve raw source location/PLZ exactly;
- never invent PLZ from city;
- retain employer/title/description/salary/publication metadata when source-backed;
- frontier scans always report `coverage_complete=False` and can never deactivate missing listings;
- cross-board duplicates remain separate JobListings but may converge on one canonical Job;
- no bypassing rate limits or access controls.

## karriere.at low-impact frontier — production proven

Files:

- `app/sources/job/karriere_at.py`
- `scripts/run_karriere_at_jobs.py`
- `tests/test_karriere_at_job_source.py`

Implementation:

- five focused searches: Konstrukteur Maschinenbau, Mechanischer Konstrukteur, Konstrukteur Sondermaschinenbau, Mechanical Design Engineer, Entwicklungsingenieur;
- first result page only;
- numeric `/jobs/<id>` stable listing identity;
- cross-query in-process dedupe;
- title-only request-budget prefilter before details;
- obvious electrical/software/sales/training/workshop titles skipped before detail requests;
- max 8 detail pages/query;
- global 0.65s minimum interval; sequential requests;
- 429 fails immediately, no aggressive retry;
- detail parser prefers public schema.org `JobPosting`; visible `Dienstort` is conservative fallback;
- actual relevance still goes through discovery gate v14 after detail acquisition;
- always coverage-incomplete.

### Production run #38

First broad-board production proof succeeded:

- incremental / partial by design / coverage degraded by design;
- 5/5 shards successful, 0 failed;
- only 35 HTTP requests total;
- 30 relevant jobs seen, 30 new;
- source-reported search counts summed to 435;
- all 30 title/detail candidates passed v14;
- 34 relevant JobLocations, 27 geo-resolved, 7 unresolved;
- 27 structured salaries, 14 annualized;
- no rate-limit or source errors.

The 30 titles include directly relevant mechanical roles such as:

- Konstrukteur / Entwicklungsingenieur Fahrzeugbau / Mechanical Engineer
- Mechanical Engineer – Konstruktion & Projektengineering
- Senior Konstrukteur Sondermaschinenbau
- Mechanical Design Engineer – Product Development
- Head of Mechanical Design
- Entwicklungsingenieur Maschinenbau

Important interpretation of run #38:

- `postal_resolved=0` is NOT a parser failure. Live karriere.at detail pages inspected after the run expose `Dienstort` such as `Stegersbach` or `Lochen am See` but no PLZ for those jobs. WohnWerk correctly keeps city-level provenance rather than inventing a postal code.
- the `konstrukteur-sondermaschinenbau` shard needing only one request and producing zero new details is expected cross-query dedupe: its first-page jobs strongly overlap earlier search frontiers. This is desired request saving, not missing coverage.
- unresolved karriere locations currently include Wels-Land, Niederranna, Schaftenau, Ranshofen, Südlich von Wien, Traboch and Wien 3. Bezirk (Landstraße). Do not invent coordinates; improve generic locality aliases/reference coverage later if worthwhile.

Karriere frontier is considered good enough. Do not add pagination/reconciliation now.

## jobs.at low-impact frontier — implemented, awaiting first production probe

Files:

- `app/sources/job/jobs_at.py`
- `scripts/run_jobs_at_jobs.py`
- `tests/test_jobs_at_job_source.py`

Current searches:

- Mechanical Engineer
- Konstrukteur Maschinenbau
- Maschinenbau Konstrukteur
- Entwicklungsingenieur
- Mechanical Design Engineer

Behavior mirrors the proven karriere frontier:

- server-rendered first search page only;
- numeric `/i/<id>` stable listing identity;
- cross-query dedupe;
- title-only request-budget filter before detail fetch;
- electrical/software/sales/training/workshop titles skipped before detail fetch;
- max 8 detail pages/query;
- global 0.75s minimum interval, sequential requests;
- 429 fails immediately;
- detail parser prefers schema.org `JobPosting` when present;
- visible-page fallback parses the public jobs.at header location;
- explicit locations like `1030 Wien, Wien, AT` preserve `postal_code=1030` rather than degrading to a generic Wien point;
- visible salary text is retained when structured salary metadata is absent;
- always `coverage_complete=False`.

Public live jobs.at pages confirm the intended low-impact surface: result pages are server-rendered, detail URLs use stable `/i/<id>`, and some results/locations explicitly expose Austrian PLZ such as `1030 Wien` and `1100 Wien`.

CI #316 passed Ruff, Compile and the full test suite after a style-only `Iterator` import correction.

## Candidate personalization / future fit

Seed CV:

> Erfahrener Maschinenbauingenieur und technischer Projektleiter mit nahezu 30 Jahren Berufserfahrung in Produktentwicklung, mechanischer Konstruktion und technischer Projektsteuerung. Umfangreiche Erfahrung von der Konzept- und Anforderungsphase über Konstruktion, Berechnung und Validierung bis zur Serienreife - insbesondere in Maschinenbau, Fahrzeug- und Sonderfahrzeugbau, Schienenfahrzeugtechnik und Vorrichtungsbau. Erfahrung sowohl in klassischen als auch in agilen Entwicklungsprojekten, unter anderem mit zweiwöchigen Sprints und regelmäßigen Team- und Abstimmungsmeetings. Langjährige Praxis in fachlicher Teamführung, Lieferantenkoordination, Lasten-/Pflichtenheften, Terminsteuerung, FEM, FMEA sowie Versuch, Montage und Inbetriebnahme.

Explicit user clarification:

- candidate is fundamentally mechanical / Maschinenbau, not electrical;
- core competence neighbourhood: mechanische Konstruktion, CAD, Bauteile/Baugruppen, machine parts, automotive/special-vehicle/rail components, chassis/suspension-like mechanical systems, product development, technical project work, supplier coordination, validation/testing and mechanically relevant assembly/commissioning;
- pure electrical engineering is explicitly outside competence and interest;
- initialize `electrical_engineering` candidate concept as strong negative (`cannot + not want`) unless user later overrides it;
- pure Electrical/Electronics roles may remain in acquisition but should rank near the bottom for this candidate;
- personal dislikes affect candidate fit/preferences, never discovery taxonomy.

Future fit architecture after corpus reaches hundreds→thousands relevant active jobs:

- normalized concepts by role/domain/task/method/tool/work condition;
- CV-seeded capability plus explicit user constraints;
- German UI with independent `Können` and `Wollen`;
- explicit answers override inference;
- vacancy feedback updates candidate fit only.

## Immediate work order

1. Pull current branch and run tests.
2. Run `python scripts/run_jobs_at_jobs.py` with defaults only; do NOT reconcile.
3. Run location resolution.
4. Inspect `job_source_stats.py jobs.at --all-titles` and `job_rejection_audit.py jobs.at`.
5. Inspect source health and actual request count.
6. Confirm live jobs.at detail parsing, especially whether explicit PLZ survives into `postal_resolved` rows and whether JSON-LD or visible fallback dominates.
7. Fix only generic parser/runtime issues from the live probe.
8. If clean, implement AMS `alle jobs` / eJob-Room next with the same low-impact title-frontier philosophy, while preserving aggregator provenance.
9. Keep karriere.at, Personio, Lever and SmartRecruiters running as independent supplementary listings and dedupe only at canonical Job level.
