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

## SmartRecruiters — correctness phase closed

### Liveness

Production liveness audit checked 43 relevant-active rows:

- live_confirmed: 43/43
- dead: 0
- unknown: 0
- missing apply URL: 0

Keep liveness independent; age alone never means closure.

### Stable republish identity

Canonical source-backed identity:

`smartrecruiters:{tenant}:jobad:{jobAdId}`

Public posting IDs remain separate lifecycle rows.

Production repair:

- 56/56 legacy rows had derivable identity
- 2 duplicate canonical groups, both clear Anton Paar republishes
- identity_backfilled=56
- merged_jobs=2
- reassigned_listings=2
- post-apply audit: needs_identity_backfill=0, duplicate_identity_groups=0

No schema migration required.

### Reconciliation #33

- success / coverage OK / 15 of 15 shards
- source_reported=411
- seen relevant=42, new=1, updated=41
- disappeared source listings=4
- listings_total=57, source_active=53
- relevant_active_listings=42, relevant_active_canonical_jobs=42
- relevant locations=42, geo_resolved=41

Remaining regional scope:

`Standort: Tirol (Außendienst & Homeoffice), Tirol, Austria`

Do not invent a city/PLZ for it.

## Discovery gate v13 — production confirmed

Current version: `profile-seed-2026-08-28-v13`.

Generic v13 changes:

- building-services support: Gebäudetechnik / HKLS / TGA / HVAC / building services/systems
- adjacent Field Service Manager
- adjacent Produktionsleiter/Fertigungsleiter/production/manufacturing manager with technical evidence
- compound German `*fertigung*` support
- HR/recruiting body boilerplate stays visible in audit evidence but does not block a technical match unless HR semantics are in the title
- hard workshop-trade exclusion for KFZ-Mechatroniker/KFZ-Techniker/automotive mechanic/technician
- prior Intern/Internship boundary fix remains; `internal` / `international` are not student-stage

### Personio reconciliation #35 validates v13

Run #35 after ENPULSION import:

- status=success, coverage=ok
- shards=14/14
- source_reported=215
- current relevant seen=15
- new=7, updated=8
- disappeared=1
- listings_total=21, source_active_listings=20
- relevant_active_listings=15 / canonical jobs=15
- relevant locations=15, geo_resolved=13, unresolved=2

The intended v13 corrections happened in production:

- Axess: `Field Service Manager` retained
- Axess: `Produktionsleiter Gerätefertigung` retained
- IAKW: `Ingenieur:in Gebäudetechnik / HKLS-Technik` retained
- Toyota: four Servicetechniker regional/nationwide variants retained
- Denzel: KFZ-Mechatroniker/KFZ-Techniker workshop roles structurally rejected

Therefore stop gate micro-calibration here unless a later corpus audit exposes a genuinely generic correctness bug.

## Personio — registry and acquisition

### Registry / domains

14 enabled tenants after ENPULSION import; legacy `isoplus-fwt-aut` remains disabled.

Adapter tries current `*.jobs.personio.com` first and legacy `*.jobs.personio.de` fallback. Do not permanently pin a tenant to the old domain.

Austria filtering requires a known Austrian locality or explicit Austria/Österreich evidence. Four-digit PLZ alone is insufficient (`8000 Zürich` regression).

### Candidate verification

Initial expansion:

- first batch: 9/10 verified and registered
- `optimuse`: 404 on both `.com` and `.de`, not inserted
- ENPULSION: verified 8 source positions / 8 Austrian positions and registered
- failed verification never auto-disables/removes a tenant

### Multilingual XML correctness — implemented after run #35

Run #35 exposed a source-data issue, not a gate issue. ENPULSION `Electrical Engineer` and `Test Engineer` appeared with zero technical support evidence even though their live public job pages contain rich engineering descriptions.

Root cause: WohnWerk fetched Personio XML only with `language=de`. Personio XML job-description fields are language-specific; English-default/English-only jobs can therefore lose their descriptions in the German feed.

Implemented fix:

- `PERSONIO_LANGUAGES = ("de", "en")`
- every healthy Personio domain is fetched in German and English
- rows are merged by stable Personio position/source-listing ID; source counts are not doubled
- German description remains canonical primary when present
- English description becomes primary only when German description is absent
- additional translated descriptions are stored only as `wohnwerk_discovery_extra_text` and participate in discovery matching without forcing mixed-language canonical display text
- `personio_xml_languages`, `personio_description_languages` and primary description language are recorded in raw payload
- verifier also checks/records both DE and EN feeds
- if one language transiently fails but the other feed remains healthy, source lifecycle coverage can still be complete because position IDs are present across the feed; language evidence remains observable

Official Personio documentation confirms that XML defaults to German and uses `?language=en` for English descriptions.

ENPULSION public pages independently confirm the missing-English-data issue:

- Electrical Engineer: design/development/integration of high-reliability electronics, supplier coordination, verification/testing, series production, automotive/rail experience
- Test Engineer: functional/environmental testing, test setups, qualification, mechanical/electrical systems

Do not solve these with generic-title promotion; recover the source descriptions instead.

### Location cleanup

`Vienna` was already an exact alias for `Wien`; Personio locality extraction now also detects the English locality token inside longer source labels such as `Austria Center Vienna`, preserving the original location text while resolving city geography to Wien.

`österreichweit` is a legitimate nationwide scope and should remain non-point geography; do not invent a centroid/city merely to make unresolved counts zero.

### CI

Multilingual Personio adapter + supplemental discovery evidence + venue locality regression passed CI #290:

- Ruff: success
- Compile: success
- Tests: 136 passed

## Candidate personalization / future fit

Candidate seed profile:

> Erfahrener Maschinenbauingenieur und technischer Projektleiter mit nahezu 30 Jahren Berufserfahrung in Produktentwicklung, mechanischer Konstruktion und technischer Projektsteuerung. Umfangreiche Erfahrung von der Konzept- und Anforderungsphase über Konstruktion, Berechnung und Validierung bis zur Serienreife - insbesondere in Maschinenbau, Fahrzeug- und Sonderfahrzeugbau, Schienenfahrzeugtechnik und Vorrichtungsbau. Erfahrung sowohl in klassischen als auch in agilen Entwicklungsprojekten, unter anderem mit zweiwöchigen Sprints und regelmäßigen Team- und Abstimmungsmeetings. Langjährige Praxis in fachlicher Teamführung, Lieferantenkoordination, Lasten-/Pflichtenheften, Terminsteuerung, FEM, FMEA sowie Versuch, Montage und Inbetriebnahme.

Broad discovery is intentionally wider than personal preference. User feedback already confirmed professionally adjacent but personally undesirable roles (e.g. Kunststoffteile construction). Never narrow acquisition from that feedback.

Future design after corpus reaches hundreds→thousands relevant jobs:

- normalized concepts by role/domain/task/method/tool/work condition
- CV-seeded profile
- German UI with independent `Können` and `Wollen`
- explicit answers override CV inference
- likely ordinal Wollen: Nein / Eher nein / Neutral / Eher ja / Ja
- vacancy feedback: Interessant / Nicht interessant, optionally Warum nicht?
- feedback adjusts candidate fit only, never discovery taxonomy

## Immediate work order

1. Pull current branch containing the multilingual Personio fix and run tests.
2. Refresh ENPULSION verification evidence so registry records DE+EN capability.
3. Reconcile Personio again.
4. Run location backfill, Personio stats and rejection audit.
5. Confirm whether ENPULSION Electrical Engineer and Test Engineer now receive their actual English technical evidence rather than zero-evidence rejection.
6. Confirm `Austria Center Vienna` resolves to Wien; nationwide `österreichweit` may remain deliberately non-point.
7. If this behaves as expected, treat Personio calibration/correctness as closed and continue tenant expansion without further gate tuning.
8. Expand Lever after Personio scale.
9. Add independent layers such as Greenhouse, Ashby, Workable and suitable employer/board sources.
10. At corpus scale, implement concept normalization, German profile review, intrinsic fit and house/job recommendations.
