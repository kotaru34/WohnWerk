# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-27 (Europe/Berlin)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`  
**Checkpoint base head before this handoff refresh:** `58f82742f1b79ba39c2d232cbb0e91e87023126c`

This file is the recovery point for continuing WohnWerk in a fresh ChatGPT/Codex context. Read it before changing architecture, re-tuning the discovery gate, or re-investigating acquisition issues that are already closed.

---

## 1. Product goal and hard invariants

WohnWerk is a private/self-hosted **Austria-first** aggregator and matcher for:

1. houses for sale;
2. job vacancies;
3. local house/job matching and ranking.

The product must not become either of these extremes:

- a tiny hand-picked job shortlist; or
- a local copy of the entire Austrian labour market.

The intended job loop is:

```text
broad external Austrian acquisition
        ↓
Austria location gate
        ↓
structural career-stage / obvious role-family gate
        ↓
high-recall professional-neighbourhood gate
        ↓
LOCAL RELEVANT JOB CORPUS
(hundreds → thousands → potentially ~10k active jobs if coverage permits)
        ↓
concept extraction + normalization
        ↓
manual profile review
(ability + willingness kept independent)
        ↓
intrinsic job_fit_score
        ↓
PostGIS house/job many-to-many matching
```

### Non-negotiable ranking/model rules

- `JobListing.status` is **source lifecycle only**.
- Professional relevance is independent and comes from `raw_payload["wohnwerk_discovery_gate"]["accepted"]`.
- A taxonomy/gate change must never masquerade as source disappearance.
- New rejected candidates are normally not durably persisted.
- Previously persisted jobs that later become irrelevant remain source-visible/source-active when the source still reports them.
- `job_fit_score` is intrinsic/recomputable from job concepts + reviewed profile.
- Geography is a separate dimension.
- Property suitability, job suitability, distance and salary evidence remain separate dimensions.
- Hard filters are never silently overridden.
- House ↔ jobs is many-to-many; do not precompute a permanent NxM matrix.
- Use PostGIS radius queries (25 / 50 / 100 / custom km).

### End-user language invariant

All WohnWerk user-facing UI must be **German**.

No Ukrainian in navigation, labels, settings, help, explanations, recommendations, status pages or profile UI. English is acceptable only where it is natural/source-derived (job titles, tools, source names). Developer docs/code/logs may be English.

---

## 2. Target professional neighbourhood

The current generalized seed is based on an experienced Austrian mechanical-engineering / technical-project profile. Treat this as a **known-capabilities lower bound**, not an exhaustive whitelist.

Broad capability neighbourhood:

- mechanical engineering;
- product development;
- mechanical design / CAD;
- technical project leadership/control;
- concepts/requirements → design/calculation/validation → series readiness;
- vehicle / special-vehicle engineering;
- rail / rolling stock;
- fixture/tooling;
- plant / special machinery;
- manufacturing / production engineering;
- supplier/interface coordination;
- schedules/milestones;
- FEM / FMEA;
- testing / validation;
- assembly / commissioning;
- technical/team leadership.

Important tool/method evidence:

- CATIA V5;
- Creo Elements;
- SolidWorks / Inventor / Siemens NX where relevant;
- CAD generally;
- FEM / FEA;
- EMC / EMV;
- FMEA;
- PDM / PLM;
- requirements / Lastenheft / Pflichtenheft;
- technical drawings;
- diagnostics / calibration;
- system integration;
- CAN / vehicle networks;
- validation / testing;
- commissioning;
- supplier/interface coordination;
- milestone/schedule management;
- series readiness.

Supporting but non-defining evidence includes SAP, MS Office, generic agile methods and generic stakeholder language.

The gate is deliberately high-recall. Final suitability comes later from normalized corpus concepts + manual ability/willingness review.

---

## 3. Acquisition philosophy and lifecycle semantics

### Coverage first

- No official API alone is **not** grounds to discard a source.
- Prefer documented public APIs/feeds where available.
- Ordinary low-rate HTTP parsing, pagination, public embedded JSON and normal browser traversal may be evaluated source-by-source.
- No CAPTCHA bypass.
- No credential theft.
- No fingerprint spoofing.
- No deliberate anti-bot evasion.
- Respect explicit source restrictions.
- Compose coverage from ATS feeds, employer pages, boards, agencies and public sources.

The KPI is **relevant Austrian vacancy coverage**, not adapter count.

### Reconciliation safety

- Failed/partial runs never mass-deactivate.
- Only complete successful reconciliation can become authoritative.
- One miss is not sufficient for disappearance/deactivation.
- Source lifecycle and professional relevance remain separate.
- Sparse updates are enrichment-only.
- Exact/provider identity is preferred; fuzzy matching belongs in a later separate confidence layer.

---

## 4. Production infrastructure

Application LXC:

```text
/opt/wohnwerk
Debian
4 cores on an i5-9300H host
DDR4
```

Database:

```text
PostgreSQL 15.16 (Debian 12)
host: 10.169.2.6
database: wohnwerk
owner: shore-keeper
PostGIS: 3.3.2
```

Do not request or print the database password.

Current production Alembic head:

```text
0006_job_source_tenants
```

No migration is required for the most recent SmartRecruiters/gate/audit work.

Important tables include:

- `sources`
- `source_shards`
- `crawl_runs`
- `crawl_shard_runs`
- `postal_codes`
- `properties`
- `property_listings`
- `jobs`
- `job_listings`
- `job_locations`
- `job_source_tenants`
- `alembic_version`

RTR Austrian PLZ reference data + BEV-derived centroids are already loaded.

A separate V100 32 GB VM exists for future optional AI inference. Core WohnWerk must not depend on it.

---

## 5. Property acquisition — stable, do not reopen absent regression

### IMMMO.at

Authoritative production reconciliation: **run #11**.

```text
status=success coverage=ok
seen=13,948
new=13,514
updated=434
disappeared=0
pages=1,167
shards=9/9
```

All 9 Bundesländer covered.

Approx. 560 synthetic/linkless fallback identities (~4%) exist and are handled conservatively. They are not grounds for declaring discovery incomplete and are excluded from normal automatic disappearance logic because their fingerprint can change.

Do not re-investigate previously fixed IMMMO issues (pagination window, sparse cards, wrapped links, count drift, late-page failure diagnostics, sparse-update erasure, synthetic identity semantics) unless live regression appears.

### s REAL

Authoritative production reconciliation: **run #16**.

```text
status=success coverage=ok
seen=314
new=6
updated=308
disappeared=0
pages=16
```

All 314 are detail-enriched.

Current deterministic IMMMO ↔ s REAL overlap in the validated snapshot was 0. Keep deterministic URL/provider-ID dedupe; do not introduce aggressive fuzzy ingestion merges.

### ImmoAds

Disabled/retired. Historical degraded run remains only for audit.

---

## 6. Job-source architecture

Current job layers:

1. Lever public postings;
2. Personio public XML;
3. SmartRecruiters public Posting API.

All three use the same general principles:

- DB-backed source/tenant/shard state;
- conservative coverage/reconciliation;
- Austria filtering before durable relevant persistence;
- professional gate before durable persistence;
- source lifecycle separate from professional relevance;
- PostGIS-capable location resolution.

### Tenant registry

`job_source_tenants` stores:

- source;
- namespace;
- tenant key;
- company;
- enabled state;
- JSON config;
- `discovered_at`;
- `last_verified_at`.

`last_verified_at` now updates automatically after a successful shard run. It means **the tenant endpoint was successfully verified**, not that the tenant currently has Austrian vacancies.

CLI:

```bash
python scripts/job_tenants.py list <source>
python scripts/job_tenants.py add <source> <tenant> "<company>"
python scripts/job_tenants.py enable <source> <tenant>
python scripts/job_tenants.py disable <source> <tenant>
python scripts/job_tenants.py config-set <source> <tenant> <key> <value>
python scripts/job_tenants.py config-unset <source> <tenant> <key>
python scripts/job_tenants.py import-json <source> <file.json>
```

Bulk import inserts missing tenants without overwriting operator-managed rows.

---

## 7. Discovery gate — current v10

File:

```text
app/jobs/discovery.py
```

Current version:

```text
profile-seed-2026-08-27-v10
```

Supporting vocabulary:

```text
app/jobs/profile_seed.py
```

### Current broad acceptance logic

In simplified form:

1. structural hard title exclusions win where appropriate;
2. strong mechanical title accepts;
3. low-relevance title rejects;
4. adjacent engineering role + engineering domain accepts unless negative context is insufficiently counterbalanced;
5. adjacent role + method/tool accepts when not negative;
6. generic title may accept with multiple domains + method;
7. method-heavy generic title may accept with >=3 methods and no negative context;
8. otherwise reject.

### Structural career-stage exclusions

Current experienced-professional corpus excludes explicit:

- student / working-student;
- apprenticeship / Lehre / Lehrstelle / Lehrausbildung / Doppellehre;
- internship / Praktikum;
- trainee;
- explicit graduate-entry / Absolvent / Berufseinsteiger / entry-level roles.

Career-stage exclusion can beat an otherwise strong mechanical title.

### Other calibrated exclusions

Already handled:

- software engineering / software PM roles;
- explicit AI/data roles;
- depot/test-operator noise;
- manual trades such as Metallfacharbeiter / Schlosser / generic Mechaniker;
- welder / Schweißer;
- procurement / purchasing / buyer roles;
- logistics roles;
- expansion-management roles;
- cutting/machining/CNC operator roles;
- generic IT project roles;
- obvious sales/HR/finance contexts.

### Important v10 fix

Commercial `sales` negative context no longer mistakes technical **after-sales service** wording for a sales role.

This fixed a real Anton Paar false negative: `Field Service Engineer – Pharma & Life Sciences` is a technical service/maintenance/commissioning/troubleshooting vacancy and must remain in the broad corpus.

Actual Sales Engineer / Sales Manager / sales-business-development roles remain negative.

---

## 8. Rejected-candidate audit

New rejected candidates are intentionally not durably persisted, but at scale we still need to detect false negatives.

The runner now stores a **bounded audit sample** (up to 50 unique rejected titles per shard) in crawl diagnostics with classification evidence such as:

- reason;
- strong title matches;
- adjacent title matches;
- domain matches;
- method/tool matches;
- negative context matches;
- low-relevance title matches.

Audit command:

```bash
python scripts/job_rejection_audit.py <source>
```

Tenant-specific:

```bash
python scripts/job_rejection_audit.py smartrecruiters-public-postings --tenant AntonPaar1
```

This is quality-control evidence, not a durable rejected-vacancy corpus.

Generic source stats also support full title output:

```bash
python scripts/job_source_stats.py <source> --all-titles
```

---

## 9. Lever — calibrated and stable

Source:

```text
lever-public-postings
```

Bootstrap tenants:

- eu:blackshark
- eu:westernacher
- global:cargo-partner
- global:qualysoft
- global:tsmg

Authoritative calibration milestone: **run #22**.

```text
status=success coverage=ok
shards=5/5
seen=6
new=0
updated=6
disappeared=0
pages=46
```

Relevant active corpus: **6**.

All 6 relevant locations resolved.

Relevant examples are TSMG autonomous-vehicle technical roles:

- Senior Autonomous Vehicle Technician;
- Autonomous Vehicle Operations Lead;
- Self-Driving Systems Specialist;
- diagnostics/calibration/technical operations variants.

Qualysoft and older Blackshark/TSMG source-history rows can remain source-active but locally irrelevant. Do not keep overfitting these five tenants.

---

## 10. Personio — calibrated, next source to scale

Source:

```text
personio-public-xml
```

Adapter:

```text
app/sources/job/personio.py
```

Current enabled bootstrap tenants:

- axess-ag
- denzel-gruppe
- easelink-gmbh
- lcm

Historical `isoplus-fwt-aut` exists in registry but was disabled because its public XML endpoint returns 404 despite the company career site existing. Treat this as a source-capability mismatch, not a parser bug.

Authoritative calibration milestone: **run #24**.

```text
status=success coverage=ok
shards=4/4
seen=8
new=1
updated=7
source_reported=80
disappeared=0
```

Relevant active corpus: **8**.

All 8 relevant locations resolved.

Relevant examples:

- Mechanical Engineer;
- Senior Mechanical Engineer;
- Requirements Engineer;
- Systems Engineer;
- Head of Electronics;
- EMC Engineer;
- two broad technical automotive mechatronics roles at Denzel.

Explicit Software Projektmanager, Digital Engineering & AI Lead and the LCM student role remain source-history where persisted but locally irrelevant.

**Next major acquisition task after the small run #31 cleanup:** build Personio bulk tenant discovery/import using the same scalable registry approach already proven on SmartRecruiters.

---

## 11. SmartRecruiters — calibrated and first scaled layer

Source:

```text
smartrecruiters-public-postings
```

Adapter:

```text
app/sources/job/smartrecruiters.py
```

Acquisition:

```text
GET /v1/companies/{tenant}/postings
country=at
destination=PUBLIC
limit=100
```

Every Austrian list posting gets a detail fetch before classification because list objects may be incomplete.

`companyDescription` is intentionally excluded from discovery text to avoid employer boilerplate creating false professional evidence.

Coverage becomes complete only when list traversal and required details complete without cap/fetch failures.

### Brainlab investigation — closed

Registry contains:

- old `Brainlab` row disabled;
- lowercase `brainlab` enabled.

The lowercase identifier is correct.

The old Salzburg `Mechanical Engineer` page remained directly accessible after its posting deadline, but current public API traversal correctly reported zero active Austrian Brainlab postings. A generic unfiltered-Austria fallback capability exists in adapter config for future proven filter gaps, but it is **not enabled for Brainlab**.

Do not re-investigate this unless current API/web evidence changes.

### First bulk SmartRecruiters batch

Data file:

```text
data/job_tenants/smartrecruiters_austria_candidates.json
```

It added:

- AntonPaar1 — Anton Paar
- IMSNanofabricationGmbH — IMS Nanofabrication
- UmdaschGroup — Umdasch / Doka
- SegulaTechnologies — SEGULA Technologies
- Aumovio — AUMOVIO
- SalesianerMiettex — Salesianer Miettex
- Kronospan — Kronospan / Kaindl
- RedBull — Red Bull
- RenesasElectronics — Renesas Electronics

Existing bootstrap enabled tenants:

- ALTEN
- ATParchitekteningenieure
- AustroHolding
- BekumGroup
- BoschGroup
- brainlab

Registry has **16 rows total** because the old `Brainlab` row remains disabled. **15 are enabled**.

---

## 12. SmartRecruiters run history and current authoritative checkpoint

### Run #29 — first 15-shard scaling run

```text
status=success coverage=ok
shards=15/15
seen=36
new=22
updated=14
source_reported=412
disappeared=0
```

This proved registry scaling, verification timestamps and 15-tenant acquisition worked.

It also exposed obvious business/operational false positives, which led to gate v9.

### Run #30 — v9 cleanup

```text
status=success coverage=ok
shards=15/15
seen=29
new=0
updated=29
source_reported=411
disappeared=0
```

v9 removed procurement/logistics/expansion/operator/welder noise but accidentally rejected an Anton Paar Field Service Engineer because the body contained `after-sales service`. That led to v10.

### Run #31 — CURRENT production checkpoint

This is the latest authoritative SmartRecruiters state as of this handoff.

```text
Run #31: reconciliation
status=success coverage=ok
shards=15/15 failed=0 pages=15
seen=34 new=5 updated=29 source_reported=411
disappeared=0
```

Current persisted/lifecycle state:

```text
listings_total=47
source_active_listings=47
relevant_active_listings=34
source_active_canonical_jobs=47
relevant_active_canonical_jobs=34
current_run_source_sightings=47
current_run_relevant=34
```

Geography:

```text
relevant_locations=34
geo_resolved=32
city_approx=32
unresolved=2
```

Unresolved source location text:

```text
2x Großraum Linz, Steyr,Wels, Austria
```

Current relevant counts by tenant:

```text
ALTEN:                     6
ATParchitekteningenieure:  3
AntonPaar1:               10
AustroHolding:             1
BekumGroup:                3
BoschGroup:                1
IMSNanofabricationGmbH:    3
Kronospan:                 1
RenesasElectronics:        3
UmdaschGroup:              3
```

Enabled tenants currently returning zero relevant rows include AUMOVIO, Red Bull, Salesianer, SEGULA and brainlab. Zero current Austrian/relevant rows does not mean a tenant is invalid if the endpoint is healthy and verified.

### Run #31 relevant titles

ALTEN:

- Experienced Test Manager Rolling Stock
- System Safety Engineer
- Technical Project Manager Engineering
- Konstrukteur Maschinenbau (NX)
- Kabelstrangentwickler - Konstrukteur
- Entwicklungsingenieur Elektrotechnik

ATP:

- Projektleiter TGA (HKLS) – Datacenter
- Projektleiter TGA (HKLS)
- Ingenieur für Planung/Baubegleitung Gebäudesysteme (TGA/HKLS/Elektro/Gebäudeautomation/Energie/BIM)

Anton Paar:

- Konstrukteur für Kunststoffteile
- Design Engineer – Plastic Components
- Team Lead Work Preparation Machining
- Hardware Design Engineer mit Auslandsbereitschaft
- Hardware Design Engineer with Willingness to Work Abroad
- Field Service Engineer Laboratory Instruments — Westösterreich
- Service Techniker
- Field Service technician
- Außendienst Service Techniker — Pharma & Life Sciences
- Field Service Engineer – Pharma & Life Sciences

Austro Holding:

- Mechanical Engineer

Bekum:

- Servicetechniker – Elektrik
- Instandhaltungstechniker
- Maschinenbautechniker

Bosch:

- Versuchsingenieur Funktionsentwicklung – Wasserstoff-Technologien

IMS Nanofabrication:

- Labortechniker Elektronik & Prototypenbau
- High Tech Assembler / Fertigungsingenieur High-Tech Manufacturing

Kronospan:

- Maschinenbautechniker — Lungötz

Renesas:

- Staff Test Engineer
- Sr Staff Functional Safety Engineer
- Staff Hardware Engineer

Umdasch:

- Konstrukteur – Schwerpunkt Metall
- Project Manager
- Digital Engineering & CAD/BIM Systems Manager

---

## 13. Run #31 rejected-audit findings — NEXT SMALL CLEANUP

The new bounded audit worked and exposed useful translation/pattern asymmetries. Do **not** blindly expand the gate; fix only clear cases.

### 13.1 Likely false negative: German compound `Servicetechniker`

Rejected Anton Paar example:

```text
Außendienst Servicetechniker Analytische Laborsysteme (w/m/d) Westösterreich
reason=insufficient_base_relevance
methods=commissioning
```

This is likely relevant and semantically very close to accepted:

- `Service Techniker (w/m/d)`
- `Field Service technician (m/f/x)`
- accepted Bekum `Servicetechniker (m/w/d) - Elektrik`

Likely issue: current adjacent technician regex relies on a word boundary before `techniker`, so German compounds such as `Servicetechniker` are not consistently treated as adjacent technical roles.

**Next action:** add a conservative service-technician title family (`servicetechniker`, `service technician`, possibly field-service variants) and regression tests. Do not make every arbitrary `*techniker` title automatically positive without domain/method evidence.

### 13.2 Translation asymmetry: `Teamleitung Arbeitsvorbereitung Zerspanung`

Rejected:

```text
Teamleitung Arbeitsvorbereitung Zerspanung (w/m/d)
reason=insufficient_base_relevance
domains=maschinenbau,manufacturing
```

English counterpart is accepted:

```text
Team Lead Work Preparation Machining (f/m/x)
```

This is a clear German/English title-pattern asymmetry.

**Next action:** add conservative German `Teamleitung` / `Teamleiter` handling for technical/manufacturing contexts, preserving the rule that generic management alone is insufficient.

### 13.3 Structural-stage asymmetry: English `Student Employee`

Rejected English chemistry vacancy:

```text
Student Employee Chemistry – Laboratory & Analytics (20 hours/week)
```

It was rejected for insufficient relevance anyway, but it did **not** hit `student_training_stage`, while the German `Studentischer Mitarbeiter...` did.

**Next action:** add `student employee` (and equivalent obvious English student-role phrasing) to structural stage patterns so future technically relevant student roles cannot leak in.

### 13.4 Do not overreact to these rejected rows

The following rejected audit examples are currently reasonable to leave rejected unless stronger evidence appears:

- Junior/Senior AI Engineer;
- AI Agentic Developer;
- Datacenter & Private Cloud Systems Engineer;
- IT Project Manager;
- SAP IT Process Consultant;
- Product Owner XRD Software;
- Area Sales Manager;
- accountant/finance roles;
- industrial varnisher;
- production worker;
- glassblower;
- trainee/student roles;
- generic Product Specialist roles with sales/software-heavy context;
- pure cutting-machine operator.

`Zerspanungstechniker` is borderline but does not need immediate promotion. The gate is a broad engineering-neighbourhood gate, not a requirement to include every skilled manufacturing trade.

---

## 14. Location-resolution issue from run #31 — NEXT SMALL CLEANUP

Current resolver handles:

- source PLZ directly;
- city-only Austrian locations via RTR names + BEV postal centroids;
- aliases such as Vienna -> Wien;
- remote + concrete city simultaneously;
- countrywide remote labels without inventing a point.

Current unresolved location:

```text
Großraum Linz, Steyr,Wels, Austria
```

Two relevant Anton Paar jobs use it.

**Do not assign a fake PLZ.**

Preferred next design:

- recognize multi-locality / `Großraum` labels conservatively;
- resolve the explicitly named Austrian localities (`Linz`, `Steyr`, `Wels`);
- derive an approximate area point from those known locality centroids (e.g. centroid/weighted aggregate);
- keep original source text and explicit resolution evidence;
- do not treat the label as an exact workplace address.

After implementing, backfill only unresolved city/area locations with the existing resolver script and verify `34/34` relevant SmartRecruiters geography if source state is otherwise unchanged.

---

## 15. Current SmartRecruiters operational commands

Update/test:

```bash
cd /opt/wohnwerk
git checkout bootstrap/austria-mvp
git pull
source .venv/bin/activate
pytest -q
```

Run full current SmartRecruiters reconciliation:

```bash
python scripts/run_smartrecruiters_jobs.py --reconcile --delay 0.2
```

Health/stats:

```bash
python scripts/source_health.py
python scripts/job_source_stats.py smartrecruiters-public-postings --all-titles
```

Rejected audit:

```bash
python scripts/job_rejection_audit.py smartrecruiters-public-postings
python scripts/job_rejection_audit.py smartrecruiters-public-postings --tenant AntonPaar1
```

Tenant state:

```bash
python scripts/job_tenants.py list smartrecruiters-public-postings
```

Location backfill after resolver changes:

```bash
python scripts/resolve_job_locations.py
```

---

## 16. Current CI / PR state at checkpoint

The latest completed CI before this handoff refresh was **CI #253**, fully green:

```text
Install   success
Ruff      success
Compile   success
Tests     success
```

PR #1 remains:

- open;
- draft;
- mergeable;
- branch `bootstrap/austria-mvp`.

The PR body is maintained as a milestone summary, but this `HANDOFF.md` is the more detailed fresh-context recovery document.

---

## 17. Exact next work order for a fresh chat

### Step 1 — small run #31 correctness cleanup

Do these before adding many more tenants:

1. fix conservative `Servicetechniker` / service-technician adjacent-title recognition;
2. fix technical German `Teamleitung Arbeitsvorbereitung...` vs English Team Lead asymmetry;
3. add `Student Employee` to structural student-stage patterns;
4. add conservative multi-locality `Großraum Linz, Steyr,Wels` resolution;
5. add regression tests for all of the above;
6. run CI;
7. production backfill locations + one SmartRecruiters reconciliation;
8. inspect `--all-titles` and rejection audit only for obvious regressions.

Expected goal after this cleanup is roughly the current 34 relevant plus the clearly restored German service-technician/team-lead rows, with all relevant locations resolved. Do not chase an exact count if upstream postings changed.

### Step 2 — stop SmartRecruiters micro-calibration

Once step 1 is validated, SmartRecruiters is considered calibrated enough. Do not keep polishing individual employers indefinitely.

### Step 3 — Personio bulk tenant discovery/import

Build the same scalable discovery/import flow used for SmartRecruiters:

- discover Austrian Personio employer identifiers from legitimate public evidence;
- verify public XML capability before enabling where practical;
- store discovery evidence/config in `job_source_tenants`;
- bulk import, not Python hardcoding;
- use `last_verified_at`;
- use rejection-audit diagnostics from the first scaled run;
- do not auto-disable on transient failures;
- explicit persistent 404/capability failures can be disabled deliberately.

### Step 4 — Lever expansion

After Personio expansion, expand Lever tenant coverage using the DB-backed registry. Do not overfit the original five calibration tenants.

### Step 5 — additional independent job layers

Evaluate/add further Austrian coverage by value, not adapter count. Candidates include:

- Greenhouse;
- Ashby;
- Workable;
- other public ATS feeds;
- employer career sites;
- ordinary Austrian boards where terms/acquisition permit;
- agencies/public sources.

AMS `alle jobs` is useful as conceptual/manual coverage evidence, but current official terms restrict automated use, so it is not the automated backend anchor.

### Step 6 — corpus concepts only after acquisition reaches meaningful scale

Do **not** start building the final concept/profile-ranking system while the corpus is still only a few dozen jobs.

Once relevant active coverage reaches at least hundreds and then grows toward thousands:

1. extract normalized concepts;
2. deduplicate aliases/morphological variants;
3. retain evidence/provenance;
4. build German profile-review UI;
5. store independent `ability` and `willingness` dimensions;
6. recompute intrinsic `job_fit_score` locally;
7. then build bidirectional PostGIS house/job recommendations.

---

## 18. Important implementation reminders

- Never put Ukrainian user-facing strings into WohnWerk UI code.
- Do not ask for the DB password.
- Do not re-open stable property acquisition absent regression.
- Do not confuse `source_active` with `relevant_active`.
- Do not persist every Austrian vacancy merely for convenience.
- Do not make the discovery gate so strict that the corpus becomes a CV keyword shortlist.
- Do not treat source page availability as proof a posting is still active; current source/API corpus is authoritative for lifecycle.
- Do not auto-disable tenants because they currently have zero Austrian jobs.
- Do not use a taxonomy change to deactivate source listings.
- Do not invent PLZ for city-only or `Großraum` jobs.
- Keep rejected audit bounded; it is diagnostic evidence, not the local rejected corpus.

---

## 19. Fresh-chat starting prompt

A new chat can start with something like:

> Continue WohnWerk from the repository checkpoint. Read `HANDOFF.md` on branch `bootstrap/austria-mvp` and inspect the latest branch/PR state. The latest production SmartRecruiters checkpoint is run #31. Start with the small run #31 cleanup listed in section 17, then move to Personio bulk tenant discovery/import. Do not reopen stable property acquisition or re-calibrate already-closed Lever/Personio/SmartRecruiters bootstrap issues unless a new regression proves it necessary.

That should be sufficient to resume without reconstructing this chat manually.
