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

Expand Lever after Personio scale; do not micro-calibrate bootstrap tenants.

## SmartRecruiters — correctness phase closed

Production liveness audit previously checked 43 relevant-active rows: 43/43 live-confirmed, zero dead/unknown and zero missing apply URLs. Age alone never means closure.

Canonical republish identity is source-backed as:

`smartrecruiters:{tenant}:jobad:{jobAdId}`

Production repair backfilled 56 identities, merged two clear Anton Paar republish canonical duplicates and reassigned two source listings. Post-apply audit reported zero missing identities and zero duplicate identity groups.

Latest production reconciliation #33:

- success / coverage OK / 15 of 15 shards
- source_reported=411
- seen relevant=42, new=1, updated=41
- disappeared source listings=4
- listings_total=57, source_active=53
- relevant_active_listings=42 / canonical jobs=42
- relevant locations=42, geo_resolved=41

Remaining regional scope `Standort: Tirol (Außendienst & Homeoffice), Tirol, Austria` intentionally remains non-point.

## Discovery gate v14

Current version: `profile-seed-2026-08-28-v14`.

### v13 — production-confirmed generic parity

v13 added/fixed:

- Gebäudetechnik / HKLS / TGA / HVAC support;
- adjacent Field Service Manager;
- adjacent Produktionsleiter/Fertigungsleiter/production/manufacturing manager with technical evidence;
- compound German `*fertigung*` support;
- HR/recruiting body boilerplate no longer blocks an otherwise technical job unless HR semantics are in the title;
- hard KFZ-Mechatroniker/KFZ-Techniker workshop-trade exclusion;
- Intern/Internship remains structural exclusion while `internal` / `international` are unaffected.

Production Personio #35 validated the intended behavior: Axess Field Service Manager and Produktionsleiter, IAKW HKLS and four Toyota Servicetechniker variants were retained; Denzel KFZ workshop roles were rejected.

### v14 — narrow evidence correctness only

Personio multilingual run #36 exposed `fem_fea` on unrelated Cloud/Business/Software/Product roles. Root cause was the old pattern `\b(?:fem|fea|finite element)\w*`, which could match EEO words such as `female`.

v14 changes only this generic evidence boundary:

- standalone `FEM` / `FEA` still match;
- `finite element` / `finite elements` still match;
- `female` does not match FEM evidence.

Regression tests cover both sides. Do not interpret v14 as a candidate-personalization change.

Stop gate micro-calibration unless a later broad-corpus audit exposes another genuinely generic correctness bug.

## Personio — multilingual acquisition production-confirmed

### Registry / domains

14 enabled tenants after ENPULSION import; legacy `isoplus-fwt-aut` remains disabled.

Adapter tries current `*.jobs.personio.com` first and legacy `*.jobs.personio.de` fallback. Austria filtering requires a known Austrian locality or explicit Austria/Österreich evidence; four-digit PLZ alone is insufficient.

Initial candidate expansion registered 9/10 verified feeds; `optimuse` remained out after 404 on both domains. ENPULSION was subsequently verified and registered.

### DE + EN XML merge

Personio XML descriptions are language-specific. WohnWerk now fetches German and English XML for each healthy tenant domain and merges rows by stable Personio position ID:

- source listings/counts are not doubled;
- German description is canonical primary when present;
- English is primary only when German description is absent;
- distinct translated description is supplemental `wohnwerk_discovery_extra_text` for discovery evidence;
- raw payload records XML/description languages and primary description language;
- verifier records both language capabilities and per-language source counts;
- one language can fail without inventing source disappearance when another healthy feed still exposes the position IDs.

### Production reconciliation #36

Multilingual production proof:

- status=success, coverage=ok
- shards=14/14
- pages=28 (DE + EN requests)
- source_reported=215, unchanged rather than doubling
- seen relevant=17
- new=2, updated=15
- disappeared=0
- listings_total=23, source_active=22
- relevant_active_listings/canonical_jobs=17

ENPULSION now has 3 relevant source jobs: Maintenance Engineer, Electrical Engineer and Test Engineer. Electrical/Test recovered only because their actual English descriptions were acquired; no generic Engineer promotion was added.

This confirms the multilingual acquisition fix. Personio correctness/calibration is considered closed except for generic bugs.

## Location normalization cleanup after #36

Run #36 proved the new Personio parser recognizes `Vienna` inside `Austria Center Vienna`, but an older canonical JobLocation row with city guess `Center Vienna` remained alongside the new resolved `wien` row because job-location enrichment treated the changed parser output as a second location.

Generic ingestion repair implemented:

- identical human-readable source `location_text` + remote flag forms a conservative source-location identity for enrichment only;
- when a newer parser interpretation resolves that same source label, an older unresolved city guess is upgraded in place;
- if both resolved and stale-unresolved rows already exist, the stale unresolved duplicate is removed through the `delete-orphan` relationship;
- no fuzzy city matching is used and locations with different source labels are never merged.

Regression tests cover both upgrade-in-place and cleanup of an already accumulated stale duplicate.

`österreichweit` remains deliberately non-point geography.

## Candidate personalization / future fit

Candidate seed CV:

> Erfahrener Maschinenbauingenieur und technischer Projektleiter mit nahezu 30 Jahren Berufserfahrung in Produktentwicklung, mechanischer Konstruktion und technischer Projektsteuerung. Umfangreiche Erfahrung von der Konzept- und Anforderungsphase über Konstruktion, Berechnung und Validierung bis zur Serienreife - insbesondere in Maschinenbau, Fahrzeug- und Sonderfahrzeugbau, Schienenfahrzeugtechnik und Vorrichtungsbau. Erfahrung sowohl in klassischen als auch in agilen Entwicklungsprojekten, unter anderem mit zweiwöchigen Sprints und regelmäßigen Team- und Abstimmungsmeetings. Langjährige Praxis in fachlicher Teamführung, Lieferantenkoordination, Lasten-/Pflichtenheften, Terminsteuerung, FEM, FMEA sowie Versuch, Montage und Inbetriebnahme.

### Explicit candidate-fit clarification from user

The candidate is fundamentally a **mechanical / Maschinenbau engineer**, not an electrical engineer. High-value fit concepts include mechanical construction/design, CAD, machine components/assemblies, control/mechanical elements, automotive parts/chassis/suspension-like components, vehicle/special-vehicle/rail work, product development, technical project work, suppliers, testing/validation and commissioning where mechanically relevant.

Electrical engineering is explicitly outside his competence/interest. For future profile initialization treat `electrical_engineering` as an explicit strong negative (`cannot + not want`) unless the user later changes it. The same principle should strongly downrank electricity/electronics-centric roles such as pure Electrical Engineer; do **not** use that personal fact to narrow acquisition/discovery.

Broad discovery can therefore legitimately keep an Electrical Engineer in the corpus while future candidate-fit ranks it near the bottom. This separation is intentional.

Other previously stated examples such as Kunststoffteile construction may be professionally adjacent but personally undesirable; those likewise belong in candidate fit/preferences, not discovery taxonomy.

Future design after corpus reaches hundreds→thousands relevant jobs:

- normalized concepts by role/domain/task/method/tool/work condition;
- CV-seeded profile plus explicit known constraints;
- German UI with independent `Können` and `Wollen`;
- explicit answers override inference;
- likely ordinal `Wollen`: Nein / Eher nein / Neutral / Eher ja / Ja;
- vacancy feedback: Interessant / Nicht interessant, optionally Warum nicht?;
- feedback adjusts candidate fit only, never discovery taxonomy.

## CI checkpoint

Runtime changes for multilingual Personio, stale location normalization repair and FEM/`female` boundary passed GitHub Actions CI #297 completely (Ruff, Compile, Tests).

## Immediate work order

1. Pull current branch and run tests.
2. Reconcile Personio once under gate v14; this reclassifies evidence with the FEM boundary fix and triggers stale source-location cleanup.
3. Run location backfill and Personio stats/rejection audit.
4. Confirm `Austria Center Vienna` has only the resolved Wien location and that `female`-boilerplate jobs no longer show `fem_fea` evidence.
5. `österreichweit` and the SmartRecruiters Tirol regional scope may remain intentionally non-point.
6. If confirmed, continue Personio tenant expansion prioritizing mechanical/CAD/product-development/technical-project employers rather than spending time on electrical-only employers.
7. Expand Lever after Personio scale.
8. Add independent Greenhouse/Ashby/Workable/employer-board layers.
9. At corpus scale implement concept normalization, German profile review, intrinsic candidate fit and house/job recommendations.
