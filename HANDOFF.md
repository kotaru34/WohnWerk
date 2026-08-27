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
- Candidate fit/preferences are also independent and recomputable.
- Gate/taxonomy changes must never masquerade as source disappearance.
- New rejected candidates are normally not durably persisted; previously persisted source-visible listings can remain active while locally irrelevant.
- Failed/partial reconciliation never mass-deactivates.
- Canonical jobs deactivate only when none of their source listings remains active.
- Do not invent Austrian PLZ/location points; approximate geography keeps provenance.
- Geography is separate from intrinsic job fit; use PostGIS rather than permanent NxM pairs.
- No CAPTCHA bypass, credential theft, fingerprint spoofing or deliberate anti-bot evasion.

## Stable properties

Do not reopen absent live regression:

- IMMMO reconciliation #11: coverage OK, 13,948 seen, 1,167 pages, 9/9 shards, disappeared=0.
- s REAL reconciliation #16: coverage OK, 314 seen, 314/314 detail-enriched, disappeared=0.
- ImmoAds retired/disabled.

## Lever

Calibration remains run #22:

- 5/5 shards, coverage OK.
- 6 relevant active jobs.
- all relevant locations resolved.
- disappeared=0.

Expand Lever after the current Personio scaling step; do not micro-calibrate bootstrap tenants.

## SmartRecruiters — production state after identity repair

### Liveness

The previous freshness concern is closed for the current corpus. Production liveness audit checked 43 relevant-active rows and found:

- live_confirmed: 43/43
- dead: 0
- unknown: 0
- missing apply URL: 0

Keep liveness as an independent sanity check; age alone never means closure.

### Stable republish identity

SmartRecruiters canonical identity is now source-backed as:

`smartrecruiters:{tenant}:jobad:{jobAdId}`

Public posting IDs remain separate `JobListing` lifecycle rows.

Production repair was run after dry-run inspection:

- listings=56
- identity_rows=56
- needs_identity_backfill=56 before apply
- duplicate_identity_groups=2
- both groups were clear Anton Paar republish pairs
- apply result: identity_backfilled=56, merged_jobs=2, reassigned_listings=2
- verification immediately after apply: needs_identity_backfill=0, duplicate_identity_groups=0

No schema migration was required.

### Reconciliation #33

- status=success, coverage=ok
- shards=15/15
- source_reported=411
- seen relevant=42
- new=1, updated=41
- disappeared source listings=4
- listings_total=57
- source_active_listings=53
- relevant_active_listings=42
- source_active_canonical_jobs=53
- relevant_active_canonical_jobs=42
- relevant locations=42, geo_resolved=41, unresolved=1

The four disappeared listings are ordinary reconciliation lifecycle cleanup, not a canonical-merge failure. The repair preserved source listings; canonical lifecycle remains correct.

Remaining unresolved location:

`Standort: Tirol (Außendienst & Homeoffice), Tirol, Austria`

Do not invent a fake city/PLZ for this regional scope.

## Discovery gate v13

Current version: `profile-seed-2026-08-28-v13`.

Run #34 Personio rejection audit exposed generic cross-source parity issues. v13 fixes them without source/company-specific rules:

- adds `building_services` support vocabulary: Gebäudetechnik / HKLS / TGA / HVAC / building services/systems;
- adds adjacent `field_service_manager`;
- adds adjacent `production_lead` for Produktionsleiter/Fertigungsleiter/production/manufacturing manager, still requiring technical support evidence;
- adds compound German Fertigung support evidence;
- ignores HR/recruiting text in body as a blocking negative while preserving it in audit evidence; HR semantics in the title still block weak matches;
- adds hard `vehicle_workshop_trade` structural exclusion for KFZ-Mechatroniker/KFZ-Techniker/automotive mechanic/technician so the older strong `mechatronik` pattern cannot incorrectly promote workshop trades.

Regression coverage confirms:

- `Ingenieur:in Gebäudetechnik / HKLS-Technik` is retained;
- service technician roles are not blocked by recruiting boilerplate;
- technical Field Service Manager with commissioning evidence is retained;
- Produktionsleiter Gerätefertigung is retained as adjacent technical management;
- KFZ-Mechatroniker and KFZ-Techniker are structurally excluded;
- HR Project Manager remains rejected even with weak engineering body vocabulary.

CI #284 passed Ruff, Compile and 132 tests.

## Personio — production state after first expansion

### Domain migration and location safety

Adapter probes current `*.jobs.personio.com` first and legacy `*.jobs.personio.de` second on every run, so domain migrations self-heal.

Austria filtering requires either:

- a known Austrian locality from the loaded postal reference, or
- explicit Austria/Österreich text.

A four-digit PLZ alone is not Austria evidence (e.g. `8000 Zürich`).

### First candidate verification/import

Initial 10 candidates were verified in production:

- 9 verified and registered;
- `optimuse` returned 404 on both `.com` and `.de` and was not inserted;
- failed verification did not disable/remove anything.

Registry after import had 14 rows total, with 13 enabled tenants and legacy `isoplus-fwt-aut` still disabled.

### Reconciliation #34

- status=success, coverage=ok
- shards=13/13
- source_reported=207
- seen relevant=10
- new=3, updated=7
- disappeared=0
- listings_total=14
- source_active_listings=14
- relevant_active_listings=11
- relevant_active_canonical_jobs=11
- relevant locations=11, all 11 resolved

Current-run relevant before v13 cleanup:

- Denzel: 2 KFZ-Mechatroniker roles (now recognized as false positives and excluded by v13)
- Easelink: Head of Electronics, Requirements Engineer, Senior Mechanical Engineer, Systems Engineer, EMC Engineer
- Gasser Partner: Expert:in BESS Integration Engineering
- Toyota Material Handling Austria: Servicetechniker Graz/Großraum Graz and Obersteiermark/Ennstal

Run #34 rejection audit also showed clear v13 false negatives such as IAKW Gebäudetechnik/HKLS, Toyota regional Servicetechniker, Axess Field Service Manager and Produktionsleiter Gerätefertigung.

### Next candidate

`enpulsion` / ENPULSION GmbH was added to `data/job_tenants/personio_austria_candidates.json` on 2026-08-28 based on its current Vienna Personio career site. Current roles include Electrical Engineer, Maintenance Engineer and Test Engineer. It has not yet been production-verified/imported.

Keep Personio scaling registry/data-driven through `scripts/verify_personio_candidates.py`; do not hardcode discovered tenants in the runner.

## Candidate personalization / future fit

Candidate seed profile:

> Erfahrener Maschinenbauingenieur und technischer Projektleiter mit nahezu 30 Jahren Berufserfahrung in Produktentwicklung, mechanischer Konstruktion und technischer Projektsteuerung. Umfangreiche Erfahrung von der Konzept- und Anforderungsphase über Konstruktion, Berechnung und Validierung bis zur Serienreife - insbesondere in Maschinenbau, Fahrzeug- und Sonderfahrzeugbau, Schienenfahrzeugtechnik und Vorrichtungsbau. Erfahrung sowohl in klassischen als auch in agilen Entwicklungsprojekten, unter anderem mit zweiwöchigen Sprints und regelmäßigen Team- und Abstimmungsmeetings. Langjährige Praxis in fachlicher Teamführung, Lieferantenkoordination, Lasten-/Pflichtenheften, Terminsteuerung, FEM, FMEA sowie Versuch, Montage und Inbetriebnahme.

User feedback confirmed that broad-discovery roles can be professionally adjacent but personally undesirable (e.g. Kunststoffteile construction). This must not narrow acquisition.

Future design:

- derive normalized concepts from a sufficiently large vacancy corpus by role/domain/task/method/tool/work condition;
- seed the profile from CV evidence;
- German UI reviews concepts on independent `Können` and `Wollen` dimensions;
- explicit answers override inferred CV assumptions;
- likely ordinal `Wollen`: Nein / Eher nein / Neutral / Eher ja / Ja;
- vacancy feedback: Interessant / Nicht interessant, optionally Warum nicht?;
- personal feedback updates candidate fit/preferences, never the acquisition taxonomy.

Do not build this UI before relevant acquisition reaches at least hundreds and preferably thousands of jobs.

## Immediate work order

1. Pull the current branch containing v13 and CI #284.
2. Run tests locally.
3. Verify/import the newly added `enpulsion` Personio candidate.
4. Reconcile Personio under v13.
5. Run Personio source stats + rejection audit and verify expected parity changes: Denzel KFZ trade roles leave relevance; HKLS/service/technical-management false negatives return where source evidence supports them.
6. Continue expanding Personio with publicly evidenced Austrian/multi-country tenants, prioritizing engineering-heavy employers.
7. After Personio expansion, expand Lever.
8. Add further independent layers such as Greenhouse, Ashby, Workable and suitable employer/board sources.
9. At hundreds→thousands relevant active jobs, implement concept extraction/normalization, German profile review, intrinsic fit and bidirectional house/job recommendations.
