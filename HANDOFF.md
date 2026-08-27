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

## SmartRecruiters — correctness closed

Production checkpoint #33:

- 15/15 shards, coverage OK, source_reported=411.
- 57 persisted listings / 53 source-active.
- 42 relevant-active source listings / 42 relevant-active canonical jobs.
- 41/42 relevant locations resolved.
- Remaining Tirol regional scope intentionally non-point.

Liveness audit previously confirmed 43/43 relevant-active rows technically live with zero dead/unknown/missing-apply cases.

Republish identity is source-backed as:

`smartrecruiters:{tenant}:jobad:{jobAdId}`

Production repair backfilled 56 identities, merged two verified Anton Paar republish canonical duplicates and reassigned two listings. Post-repair audit reports zero duplicate identity groups.

## Discovery gate v14 — correctness closed

Current version: `profile-seed-2026-08-28-v14`.

v13 generic parity was production-confirmed:

- Gebäudetechnik / HKLS / TGA / HVAC support;
- Field Service Manager parity;
- Produktionsleiter/Fertigungsleiter/production/manufacturing management with technical evidence;
- compound German `*fertigung*` support;
- HR/recruiting body boilerplate does not block otherwise technical jobs unless HR semantics are in the title;
- KFZ-Mechatroniker / KFZ-Techniker workshop roles are hard structural exclusions;
- true Intern/Internship remains excluded while `internal` / `international` are unaffected.

v14 is only an evidence-boundary correction: the old FEM regex could interpret EEO words such as `female` as `fem_fea`. Standalone FEM/FEA and finite element(s) still match; `female`/`feminine` do not.

Do not micro-calibrate the gate further unless a later broad-corpus audit exposes another genuinely generic correctness problem. Candidate preference never belongs in this gate.

## Personio — correctness/calibration closed on production #37

### Adapter / verification semantics

- Probe current `*.jobs.personio.com` first, legacy `.jobs.personio.de` second.
- Fetch DE + EN XML and merge by stable Personio position ID.
- Source counts/listings do not double across languages.
- German description remains canonical primary when present; English is primary only when German is absent.
- Distinct secondary translation may be stored as `wohnwerk_discovery_extra_text` for discovery evidence only.
- Austria requires a known Austrian locality or explicit Austria/Österreich; four-digit PLZ alone is insufficient.
- Failed candidate verification never disables/removes an existing tenant.

### Production #37

Final v14 production proof:

- status=success, coverage=ok
- shards=14/14, pages=28
- source_reported=215
- current relevant seen=17
- new=0, updated=17, disappeared=0
- listings_total=23, source_active=22
- relevant_active_listings=17 / canonical jobs=17
- relevant_locations=17, geo_resolved=16
- only Personio unresolved relevant location: `österreichweit`, intentionally non-point

The two generic #36 regressions are confirmed fixed in #37:

1. stale `Center Vienna` is gone; `Austria Center Vienna` is represented by its resolved Wien interpretation rather than duplicate parser-era JobLocations;
2. unrelated Cloud/Full-Stack/Product/Business jobs no longer receive fake `fem_fea` evidence from English EEO text.

Personio correctness/calibration is therefore CLOSED. Further Personio work is tenant scaling, not gate tuning.

### Personio registry / candidates

Current enabled production registry before next expansion: 14 tenants; legacy `isoplus-fwt-aut` remains disabled. `optimuse` previously returned 404 on both domains and was never inserted.

`data/job_tenants/personio_austria_candidates.json` now also contains:

- `teamstyria` / Team Styria Werkstätten GmbH

Reason: current Styria Personio feed is a real industrial/manufacturing watchlist. Current roles include CNC production of Maschinenbauteile plus `Arbeitsvorbereiter:in Holzmanufaktur` with CAD construction and technical drawings. The current CAD role is wood-industry and is NOT treated as evidence that it personally fits the candidate. The feed is useful because future mechanical/manufacturing roles can appear there.

Next production step for Personio is verify/apply Team Styria, then reconcile. Do not expect or force a relevant job count increase if the current titles remain outside the mechanical-engineering neighbourhood.

## Lever — scaling foundation

Calibrated production remains run #22:

- 5/5 shards, coverage OK.
- 6 relevant active jobs.
- all relevant locations resolved.
- disappeared=0.

Existing runner bootstrap seeds remain for backward compatibility:

- `eu:blackshark`
- `eu:westernacher`
- `global:cargo-partner`
- `global:qualysoft`
- `global:tsmg`

Do not hardcode newly discovered employers into `DEFAULT_TENANTS`.

### New data/registry-driven verifier

Added:

- `data/job_tenants/lever_austria_candidates.json`
- `scripts/verify_lever_candidates.py`
- `tests/test_lever_candidate_verifier.py`

The candidate inventory currently includes the five existing bootstrap tenants as a baseline so production can backfill explicit capability evidence without changing their operator-managed state. New discoveries should be appended to this file rather than to runner code.

Verifier semantics:

- candidate identity is `(namespace, tenant)` where namespace is `eu` or `global`;
- uses the matching documented public Lever Postings API endpoint;
- traverses pagination to completion rather than trusting the first page;
- reports total published source positions and Austrian positions;
- a healthy feed with 0 current Austrian vacancies is still a verified endpoint;
- hitting `hard_max_pages` while pages remain full is incomplete and therefore NOT verified;
- malformed/error feeds are not verified;
- `--apply` inserts verified missing rows or refreshes only `lever_feed_verification` + `last_verified_at` on existing rows;
- existing company/enabled/discovery/operator configuration is preserved;
- failed verification never disables/removes a tenant.

CI #303 passed Ruff, Compile and the full test suite after the verifier/import tests were corrected to load the CLI module without turning `scripts/` into a Python package.

### Lever discovery strategy

Current web discovery shows Lever has many excellent mechanical/CAD/chassis/product-development roles globally, including jobs whose task vocabulary is almost ideal for the candidate, but the currently found ones are outside Austria. Do not add Germany/Switzerland/US-only employers merely because the role content is attractive.

Austria Lever density appears lower than Personio/other ATS sources for this mechanical niche. Continue searching, but prefer real Austrian technical presence and current source evidence over registry size.

## Candidate personalization / future fit

Seed CV:

> Erfahrener Maschinenbauingenieur und technischer Projektleiter mit nahezu 30 Jahren Berufserfahrung in Produktentwicklung, mechanischer Konstruktion und technischer Projektsteuerung. Umfangreiche Erfahrung von der Konzept- und Anforderungsphase über Konstruktion, Berechnung und Validierung bis zur Serienreife - insbesondere in Maschinenbau, Fahrzeug- und Sonderfahrzeugbau, Schienenfahrzeugtechnik und Vorrichtungsbau. Erfahrung sowohl in klassischen als auch in agilen Entwicklungsprojekten, unter anderem mit zweiwöchigen Sprints und regelmäßigen Team- und Abstimmungsmeetings. Langjährige Praxis in fachlicher Teamführung, Lieferantenkoordination, Lasten-/Pflichtenheften, Terminsteuerung, FEM, FMEA sowie Versuch, Montage und Inbetriebnahme.

Explicit user clarification:

- candidate is fundamentally mechanical / Maschinenbau, not electrical;
- core positive competence neighbourhood: mechanische Konstruktion, CAD, Bauteile/Baugruppen, machine parts, automotive/special-vehicle/rail components, chassis/suspension-like mechanical systems, product development, technical project work, supplier coordination, validation/testing and mechanically relevant assembly/commissioning;
- pure electrical engineering is explicitly outside competence and interest;
- initialize future `electrical_engineering` candidate concept as strong negative (`cannot + not want`) unless user later overrides it;
- pure Electrical/Electronics roles can remain in broad acquisition but should rank near the bottom for this candidate.

Other personal dislikes (e.g. Kunststoffteile construction) likewise affect candidate fit/preferences, never discovery taxonomy.

Future fit architecture after corpus reaches hundreds→thousands relevant active jobs:

- normalized concepts by role/domain/task/method/tool/work condition;
- CV-seeded capability plus explicit user constraints;
- German UI with independent `Können` and `Wollen`;
- explicit answers override inference;
- likely ordinal `Wollen`: Nein / Eher nein / Neutral / Eher ja / Ja;
- vacancy feedback: Interessant / Nicht interessant, optionally Warum nicht?;
- feedback updates candidate fit only.

## Immediate work order

1. Pull current branch and run tests.
2. Dry-verify Team Styria Personio candidate; if healthy, apply it.
3. Dry-run `verify_lever_candidates.py` across the five baseline tenants; inspect namespace/API/page/source/Austria counts.
4. If verification looks sane, apply Lever verification evidence; this should refresh existing rows rather than create duplicates.
5. Reconcile Personio after Team Styria import and Lever after verifier refresh.
6. Run source health/stats/rejection audits; do not tune gate for expected non-fit industrial/IT roles.
7. Continue sourcing actual Austrian mechanical/CAD/product-development employers across Personio and Lever, but switch to additional ATS/source layers when marginal density drops.
8. Next independent acquisition layers: Greenhouse, Ashby, Workable and suitable employer/job-board sources.
9. At corpus scale implement normalized concept extraction, German profile review, intrinsic candidate fit and house/job recommendations.
