# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-27 (Europe/Berlin)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`  

This file is the authoritative recovery point for continuing WohnWerk in a fresh ChatGPT/Codex context.

## Product direction and core invariants

WohnWerk is a private/self-hosted Austria-first house + job acquisition, personalization and matching system.

Non-negotiable architecture:

- All end-user UI is German.
- Never ask for or print DB passwords.
- `JobListing.status` is source lifecycle only.
- Professional-neighbourhood relevance is independent and stored in `raw_payload["wohnwerk_discovery_gate"]`.
- Application liveness/freshness is a separate dimension from source lifecycle and professional relevance.
- A gate/taxonomy change must never masquerade as source disappearance.
- New rejected job candidates are normally not durably persisted; previously persisted source-visible rows can remain source-active while locally irrelevant.
- Failed/partial reconciliation never mass-deactivates.
- Canonical jobs deactivate only when none of their source listings remains active.
- Do not invent Austrian PLZ/location points. Approximate city/area geography keeps provenance.
- Intrinsic job fit is person-specific and recomputable; geography is separate.
- House/job relationships are queried through PostGIS rather than materializing permanent NxM pairs.
- No CAPTCHA bypass, credential theft, fingerprint spoofing or deliberate anti-bot evasion.

## Stable property acquisition

Property acquisition remains stable and should not be reopened absent a live regression:

- IMMMO reconciliation run #11: coverage OK, 13,948 seen, 1,167 pages, 9/9 shards, `disappeared=0`.
- s REAL reconciliation run #16: coverage OK, 314 seen, 314/314 detail-enriched, `disappeared=0`.
- ImmoAds remains retired/disabled.

## Lever

Lever calibration remains stable at run #22:

- 5/5 shards successful, coverage OK.
- 6 relevant active vacancies.
- all relevant locations resolved.
- `disappeared=0`.

Do not micro-calibrate the original bootstrap tenants. Expand Lever only after the current Personio scaling step.

## SmartRecruiters — calibrated, liveness-validated, republish identity implemented

Production reconciliation run #32:

- 15/15 shards successful, coverage OK.
- 411 source-reported Austrian postings.
- 56 source-active persisted listings.
- 43 relevant-active persisted rows; 41 current-run relevant rows.
- 42/43 relevant locations resolved; the remaining unresolved label was `Standort: Tirol (Außendienst & Homeoffice), Tirol, Austria`.
- `disappeared=0`.

Gate v11 restored the intended `Servicetechniker` compound and technical `Teamleitung` parity, added English `Student Employee` structural exclusion, and implemented conservative multi-locality `Großraum` resolution.

### Liveness result

The post-run-32 liveness concern is closed for the current corpus.

Production `scripts/job_liveness_audit.py` result:

- checked relevant-active SmartRecruiters rows: 43.
- `live_confirmed`: 43/43.
- dead: 0.
- unknown: 0.
- missing apply URL: 0.
- released age: 27 at 0–30d, 9 at 31–90d, 6 at 91–180d, 1 at 181–365d.

The specific Anton Paar `Konstrukteur für Kunststoffteile (w/m/d)` was released 2026-08-14, had a live public posting and a live SmartRecruiters OneClick apply flow. The older Google-visible page was not evidence of a currently dead vacancy.

Keep the liveness audit as an independent sanity check; do not reject jobs based on age alone.

### Republish/canonical identity

The liveness audit exposed genuine republish semantics: multiple Anton Paar public posting IDs/releases can lead to the same underlying application publication. Exact-URL canonical dedupe is therefore insufficient over time.

Implemented source-backed SmartRecruiters stable identity:

- `app/jobs/identity.py` defines `smartrecruiters:{tenant}:jobad:{jobAdId}`.
- `app/sources/job/smartrecruiters.py` writes explicit `wohnwerk_stable_identity` while preserving posting ID as `source_listing_id`.
- `app/ingestion/jobs.py` reuses an existing canonical `Job` by stable identity before falling back to exact URL.
- Legacy stored SmartRecruiters payloads can derive the identity from tenant + `smartrecruiters_job_ad_id` even before explicit backfill.
- `scripts/job_stable_identity_repair.py` audits existing duplicate canonical jobs; it is dry-run by default and requires `--apply` to backfill/merge.
- The repair survivor is the newest released/current listing; source listings are reassigned, source history remains intact, and canonical lifecycle remains correct because a canonical job stays active while any attached listing is active.
- No schema/Alembic migration is required for this payload-backed identity.

Do **not** run repair `--apply` until the production dry-run output is inspected and each duplicate group is clearly the same source job ad.

### Gate v12 correctness

Gate version is now `profile-seed-2026-08-27-v12`.

Fixed the generic internship regex that previously allowed `intern(?:ship)?\w*` to misclassify `internal` and `international` as student-stage:

- true `Intern` / `Internship` remains structurally excluded;
- `Supervisor Mechanik - international` is no longer falsely excluded;
- `Internal Auditor` is no longer student-stage and remains rejected for ordinary relevance reasons.

This is the last generic SmartRecruiters gate correctness fix before moving acquisition focus to Personio.

## Personio — next acquisition layer to scale

Calibration checkpoint remains run #24:

- 4/4 enabled bootstrap tenants successful.
- 80 source-reported positions.
- 8 relevant active vacancies.
- all relevant locations geographically resolved.
- `disappeared=0`.

Bootstrap tenants: `easelink-gmbh`, `axess-ag`, `lcm`, `denzel-gruppe`.

The old `isoplus-fwt-aut` tenant remains disabled because its public XML capability was persistently unavailable (404); do not reinterpret transient errors as automatic disable reasons.

### Personio domain migration safety

Personio is migrating career domains from `*.jobs.personio.de` to `*.jobs.personio.com`, while XML integrations cannot safely assume an automatic redirect.

WohnWerk now handles both:

- current domain `*.jobs.personio.com` first;
- legacy `*.jobs.personio.de` fallback;
- the successful endpoint is recorded in run/verification evidence;
- runtime remains self-healing and retries the current domain on later runs instead of permanently pinning a legacy endpoint.

### Austria filtering safety

Personio office filtering now requires explicit Austrian evidence:

- a known locality from the loaded Austrian postal reference, or
- explicit `Austria` / `Österreich` text.

A four-digit postal code alone is **not** Austria evidence, because Switzerland also uses four-digit postal codes. Regression coverage explicitly rejects `8000 Zürich`.

### Bulk candidate verification/import workflow

Added `data/job_tenants/personio_austria_candidates.json` with the first 10 publicly evidenced Austrian/multi-country Personio candidates:

- `toyota-material-handling-austria-gmbh`
- `iakw`
- `hitzler`
- `optimuse`
- `gasser-partner`
- `prewave`
- `wwp`
- `schwer-fittings-gmbh`
- `anyline-gmbh`
- `tenics`

Added `scripts/verify_personio_candidates.py`:

- dry-run by default;
- probes `.com` then `.de` public XML;
- requires a valid Personio XML feed;
- reports source positions and Austrian positions;
- zero current Austrian positions can still be a healthy verified endpoint;
- `--apply` registers only verified missing tenants and refreshes `last_verified_at`/verification evidence on existing ones;
- preserves operator-managed enable/disable/company/discovery configuration;
- failed verification never disables or removes an existing tenant.

This is intentionally registry/data-driven. Do not hardcode bulk discovered tenants into the runner.

## Job personalization / future fit layer

The father/candidate profile currently used as the seed is:

> Erfahrener Maschinenbauingenieur und technischer Projektleiter mit nahezu 30 Jahren Berufserfahrung in Produktentwicklung, mechanischer Konstruktion und technischer Projektsteuerung. Umfangreiche Erfahrung von der Konzept- und Anforderungsphase über Konstruktion, Berechnung und Validierung bis zur Serienreife - insbesondere in Maschinenbau, Fahrzeug- und Sonderfahrzeugbau, Schienenfahrzeugtechnik und Vorrichtungsbau. Erfahrung sowohl in klassischen als auch in agilen Entwicklungsprojekten, unter anderem mit zweiwöchigen Sprints und regelmäßigen Team- und Abstimmungsmeetings. Langjährige Praxis in fachlicher Teamführung, Lieferantenkoordination, Lasten-/Pflichtenheften, Terminsteuerung, FEM, FMEA sowie Versuch, Montage und Inbetriebnahme.

User feedback confirmed that many broad-discovery titles are professionally adjacent but personally undesirable (for example Kunststoffteile construction). This is expected and must **not** narrow the acquisition gate.

Future personalization design already agreed:

- Extract/normalize concepts from the sufficiently large vacancy corpus by role, domain, task, method, tool and work condition.
- Seed the candidate profile from CV evidence.
- Review concepts in German UI with independent `Können` and `Wollen` dimensions.
- Explicit user answers override inferred CV assumptions.
- `Wollen` should likely use an ordinal scale (`Nein / Eher nein / Neutral / Eher ja / Ja`) rather than only boolean; `Können` can remain simpler if useful.
- Vacancy feedback should support `Interessant` / `Nicht interessant` and optionally `Warum nicht?` to update concept preferences.
- A broad-discovery vacancy can remain in the corpus while receiving a very low candidate-specific fit score.
- Do not modify discovery taxonomy from personal preference feedback.

Do not build this fit/profile UI before relevant acquisition reaches at least hundreds and preferably thousands of vacancies; concept vocabulary should be corpus-informed rather than frozen from the current tiny sample.

## CI checkpoint

Code through commit `90ab25bb69f84d0c88c02fa67b8ef0a2dec8cf3b` passed GitHub Actions CI #279 completely:

- Ruff: success
- Compile: success
- Tests: success

The subsequent HANDOFF-only commit should not be interpreted as changing runtime semantics.

## Immediate production work order

On `/opt/wohnwerk`, after pulling the current branch:

1. Run the test suite.
2. Run SmartRecruiters stable-identity repair **dry-run only** and inspect all reported duplicate groups.
3. If groups are semantically correct, run the repair with `--apply`, then re-run the dry audit to confirm zero duplicate identity groups.
4. Reconcile SmartRecruiters and confirm source listings remain preserved while canonical job count is no longer inflated by republishes.
5. Run Personio candidate verifier dry-run.
6. Run Personio verifier `--apply`; only healthy feeds are inserted/refreshed.
7. Run Personio reconciliation, source health, full title stats and rejection audit.
8. Inspect Personio results for generic correctness issues only; do not restart source-specific micro-calibration.
9. Expand Personio discovery batch further, then move to Lever expansion.
10. After Lever, add further independent layers such as Greenhouse, Ashby, Workable and suitable employer/board sources.
11. Only after the relevant Austrian corpus reaches hundreds → thousands, implement concept extraction/normalization, German profile review, intrinsic candidate fit and bidirectional house/job recommendations.

Exact operational commands should be supplied in the active chat and production outputs inspected before any destructive repair step.
