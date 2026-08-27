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

Production #33:

- 15/15 shards, coverage OK, source_reported=411.
- 53 source-active listings.
- 42 relevant-active canonical jobs.
- 41/42 relevant locations resolved.
- Remaining Tirol regional scope intentionally non-point.

Liveness previously confirmed 43/43 relevant-active rows technically live.

Republish identity is source-backed as `smartrecruiters:{tenant}:jobad:{jobAdId}`. Production repair backfilled 56 identities, merged two verified Anton Paar republish canonical duplicates and left zero duplicate identity groups.

## Discovery gate v14 — correctness closed

Current version: `profile-seed-2026-08-28-v14`.

v13 generic parity was production-confirmed for HKLS/building-services, technical field service and production management while structurally excluding KFZ workshop trades. v14 only corrects the FEM evidence boundary: `FEM`, `FEA` and `finite element(s)` match; English EEO words such as `female` do not.

Do not micro-calibrate the gate further unless a later broad-corpus audit exposes another genuinely generic correctness problem. Candidate preference never belongs in this gate.

## Personio — correctness/calibration closed on production #37

Adapter semantics:

- current `*.jobs.personio.com` first, legacy `.jobs.personio.de` fallback;
- fetch DE + EN XML and merge by stable Personio position ID;
- source counts/listings do not double across languages;
- German description remains canonical primary where present; English fills missing descriptions and can provide supplemental discovery evidence;
- Austria requires a known Austrian locality or explicit Austria/Österreich evidence;
- failed verification never disables/removes an existing tenant.

Production #37:

- status=success, coverage=ok
- shards=14/14, pages=28
- source_reported=215
- current relevant seen=17
- new=0, updated=17, disappeared=0
- 22 source-active listings / 17 relevant-active canonical jobs
- relevant_locations=17, geo_resolved=16
- only unresolved relevant Personio location: `österreichweit`, intentionally non-point

Run #37 confirms both generic #36 repairs: stale `Center Vienna` is gone and unrelated English vacancies no longer receive fake `fem_fea` evidence.

Personio correctness/calibration is CLOSED. Keep the adapter as a supplementary clean feed; do not spend primary acquisition effort manually discovering employers one by one.

## Lever — correctness stable, scaling no longer primary

Production remains #22:

- 5/5 shards, coverage OK
- 6 relevant active jobs
- all relevant locations resolved
- disappeared=0

A registry-driven candidate verifier exists:

- `data/job_tenants/lever_austria_candidates.json`
- `scripts/verify_lever_candidates.py`
- regression tests for namespace identity, complete traversal and capped/incomplete rejection

Existing five bootstrap tenants remain for backward compatibility. New tenants should not be hardcoded into the runner.

Manual/bespoke Lever tenant discovery is no longer a primary scaling path. Keep Lever as a supplementary source and only add tenants when discovery can be automated or there is clear high-value Austrian coverage.

## PRIMARY JOB ACQUISITION STRATEGY — broad Austrian job boards first

This is now the dominant architecture priority.

The project had over-focused on ATS tenant feeds (Personio/Lever/SmartRecruiters). Those are useful because they are structured and clean, but they are not sufficient for market-wide Austrian coverage. The primary corpus should come from large Austria-wide job search platforms that already aggregate thousands of employers and often expose location/PLZ detail.

Current public-web validation on 2026-08-28:

1. **AMS `alle jobs` / eJob-Room**
   - official Austrian public employment search;
   - supports `Ort, PLZ, Bundesland`;
   - `alle jobs` combines AMS-managed vacancies, eJob-Room self-service postings and jobs gathered from the internet, plus public administration and selected neighbouring-country sources;
   - potentially the broadest single Austria discovery layer;
   - because it is itself an aggregator, source provenance and duplicate handling require special care.

2. **karriere.at**
   - broad Austrian marketplace with very high engineering density;
   - current search shows >1,000 `Mechanical Engineer` results;
   - `Mechanischer Konstrukteur` results contain many directly relevant roles;
   - current example: PEISCHL Fahrzeugbau `Konstrukteur / Entwicklungsingenieur Fahrzeugbau / Mechanical Engineer` with 3D CAD, Bauteile/Baugruppen, Fertigungszeichnungen, Stücklisten and Serienreife — very close to the target profile;
   - location often includes city/district and sometimes postal-code-formatted Wien locations.

3. **jobs.at**
   - currently exposes >1,100 `Metall & Maschinenbau` jobs overall;
   - current Wien Maschinenbau search shows ~150 jobs;
   - public result pages expose location, employment form, salary and sometimes PLZ (`1100 Wien`, `1030 Wien`, etc.);
   - current example: Plasser & Theurer `Konstrukteur:in Senior Maschinenbau` with Getriebe, Antriebsstränge, mechanische Baugruppen, 3D/detail drawings.

4. **willhaben Jobs**
   - currently around 15.7k jobs across Austria;
   - broad consumer-facing job marketplace with filters by title, location/region, Bundesland/Bezirk, employment type and position level;
   - strong candidate for large coverage once public pagination/detail semantics are mapped conservatively.

5. **StepStone Austria**
   - current `Konstrukteur Maschinenbau` search shows roughly 340 jobs;
   - result pages expose city and sometimes explicit PLZ such as `1030 Wien`;
   - useful independent layer with likely overlap that can help canonical dedupe and freshness confirmation.

### Broad-board adapter requirements

For each board:

- use a stable public listing ID or conservative stable identity;
- preserve raw source location/PLZ exactly;
- never invent PLZ from city;
- retain source URL, employer, title, description, salary where defensible and publication metadata where present;
- reconcile only when coverage is provably complete;
- retain separate source listings across boards even when they map to the same canonical Job;
- keep request volume low and never bypass access controls.

### Implemented first broad-board source: karriere.at low-impact frontier

Files:

- `app/sources/job/karriere_at.py`
- `scripts/run_karriere_at_jobs.py`
- `tests/test_karriere_at_job_source.py`

Implementation intentionally mirrors a human quick scan rather than a full-site crawl:

- five focused first-page searches: `Konstrukteur Maschinenbau`, `Mechanischer Konstrukteur`, `Konstrukteur Sondermaschinenbau`, `Mechanical Design Engineer`, `Entwicklungsingenieur`;
- no pagination yet;
- numeric `/jobs/<id>` is the stable source listing identity;
- job IDs are deduplicated across the five search shards during a run;
- a cheap title-only request-budget prefilter decides whether a detail page is worth opening;
- obvious electrical/software/sales/training/workshop titles are skipped before detail requests;
- maximum 8 detail pages per search shard by default;
- a global 0.65-second minimum interval serializes all search/detail requests;
- 429 is treated as a failure, not retried aggressively;
- detail parsing prefers public `schema.org/JobPosting` JSON-LD for employer, description, salary, location and PLZ;
- visible `Dienstort` is only a conservative fallback when structured location is absent;
- the adapter always reports `coverage_complete=False`, so it is discovery-only and cannot deactivate missing listings;
- real relevance still goes through the normal v14 discovery gate after detail acquisition; the title prefilter exists only to save HTTP requests.

CI #310 passed Ruff, Compile and the full test suite for this implementation.

### Next board order

1. Production-prove this karriere.at frontier with one low-impact run.
2. Implement `jobs.at` using the same first-page/title-gated pattern.
3. Then AMS `alle jobs` / eJob-Room.
4. Add willhaben Jobs and StepStone after the first two broad sources are stable.

Do not return to manual ATS tenant collection as the main path.

## Candidate personalization / future fit

Seed CV:

> Erfahrener Maschinenbauingenieur und technischer Projektleiter mit nahezu 30 Jahren Berufserfahrung in Produktentwicklung, mechanischer Konstruktion und technischer Projektsteuerung. Umfangreiche Erfahrung von der Konzept- und Anforderungsphase über Konstruktion, Berechnung und Validierung bis zur Serienreife - insbesondere in Maschinenbau, Fahrzeug- und Sonderfahrzeugbau, Schienenfahrzeugtechnik und Vorrichtungsbau. Erfahrung sowohl in klassischen als auch in agilen Entwicklungsprojekten, unter anderem mit zweiwöchigen Sprints und regelmäßigen Team- und Abstimmungsmeetings. Langjährige Praxis in fachlicher Teamführung, Lieferantenkoordination, Lasten-/Pflichtenheften, Terminsteuerung, FEM, FMEA sowie Versuch, Montage und Inbetriebnahme.

Explicit user clarification:

- candidate is fundamentally mechanical / Maschinenbau, not electrical;
- core competence neighbourhood: mechanische Konstruktion, CAD, Bauteile/Baugruppen, machine parts, automotive/special-vehicle/rail components, chassis/suspension-like mechanical systems, product development, technical project work, supplier coordination, validation/testing and mechanically relevant assembly/commissioning;
- pure electrical engineering is explicitly outside competence and interest;
- initialize `electrical_engineering` candidate concept as strong negative (`cannot + not want`) unless user later overrides it;
- pure Electrical/Electronics roles can remain in broad acquisition but should rank near the bottom for this candidate;
- other personal dislikes affect candidate fit/preferences, never discovery taxonomy.

Future fit architecture after corpus reaches hundreds→thousands relevant active jobs:

- normalized concepts by role/domain/task/method/tool/work condition;
- CV-seeded capability plus explicit user constraints;
- German UI with independent `Können` and `Wollen`;
- explicit answers override inference;
- vacancy feedback updates candidate fit only.

## Immediate work order

1. Pull current branch; expected checkpoint includes karriere.at frontier and CI #310 green.
2. Run `pytest -q`.
3. Run `python scripts/run_karriere_at_jobs.py` with defaults only; do NOT use reconciliation.
4. Resolve job locations and inspect `job_source_stats.py karriere.at --all-titles`, `job_rejection_audit.py karriere.at`, and `source_health.py`.
5. Confirm request count remains low, at least some live titles parse, JSON-LD/detail fields are populated where available, and any PLZ is source-provided rather than inferred.
6. Fix only generic parser/runtime issues exposed by the live run; do not tune discovery to one board.
7. Then implement `jobs.at` using the same low-impact search-frontier pattern.
