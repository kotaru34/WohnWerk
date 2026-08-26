# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-27 (Europe/Berlin)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`  
**Pre-checkpoint branch head:** `9c4dfc352e9ff600ff76665418dc8ddce04cec88`

This file is the recovery point for continuing WohnWerk in a fresh ChatGPT/Codex context. Read this file before changing architecture or re-investigating acquisition issues that are already closed.

---

## 1. Product goal

WohnWerk is a private/self-hosted Austria-first system that aggregates:

1. **houses for sale**, and
2. **job vacancies**,

then matches them geographically using Austrian postal codes and PostGIS.

The next major product milestone after this checkpoint is the **job ingestion pipeline**. Property acquisition now has two validated live sources with successful full reconciliation.

Longer-term UI target:

- `Häuser`
- `Jobs`
- `Matching`
- `Skills/Profil`

Initial matching target:

- house -> jobs within 25 / 50 / 100 / custom km
- job -> houses within the same radii
- PLZ-centroid distance is acceptable for the MVP
- use PostGIS `ST_DWithin` + GiST; do not precompute an NxM matrix

---

## 2. Non-negotiable acquisition philosophy

WohnWerk is **coverage-first / high-recall**.

The design goal is to actively avoid missing publicly available houses/jobs. A source integration must not be weakened into “fetch a convenient number of records and stop”. Search alerts may be supplemental, but they are not authoritative coverage.

### Coverage invariants

1. A failed or partial shard must **never** cause mass deactivation.
2. Full reconciliation is authoritative only when every enabled shard reports complete coverage and no result cap was hit.
3. Exit code `0` by itself does not mean coverage is complete.
4. Source discovery and canonical deduplication are separate concerns.
5. Preserve source listing records for provenance even when several sources map to one canonical entity.
6. Sparse updates are **enrichment-only**: they must not erase richer metadata already known.
7. Live offset-paginated indexes can move records during a scan; absence must therefore be treated conservatively.
8. First successful reconciliation establishes a baseline. A single later miss is not enough to deactivate a listing.
9. Synthetic/unstable fallback identities must not be automatically deactivated from normal reconciliation misses.
10. Source counts are sanity checks, not necessarily immutable snapshots.
11. Never bypass CAPTCHAs, spoof fingerprints, steal credentials, or implement anti-bot evasion.
12. Respect source terms and legal constraints. Compose coverage from permissible acquisition layers rather than evading restrictions.

### Current deactivation model

`reconcile_missing_listings()` deactivates only after consecutive successful reconciliation history. A listing must be absent from the current successful reconciliation and not have been seen since before the previous successful reconciliation began.

IMMMO synthetic fallback identities are excluded from automatic deactivation because their fingerprint can change when mutable card metadata changes.

---

## 3. Deployment / infrastructure

### Application LXC

Project path:

```bash
/opt/wohnwerk
```

Current application container allocation:

- Debian LXC
- 4 CPU cores
- host CPU family: Intel i5-9300H
- DDR4

MVP guidance:

- a few lightweight HTTP workers are fine
- 1–2 browser contexts only where genuinely needed
- no Celery/Redis unless later workload proves it necessary
- extra CPU is for local parsing/normalization/concurrency, not for hammering sources

### Environment

Typical `.env`:

```env
WOHNWERK_DATABASE_URL=postgresql+psycopg://shore-keeper:<PASSWORD>@10.169.2.6:5432/wohnwerk
WOHNWERK_COUNTRY_CODE=AT
WOHNWERK_AI_ENABLED=false
```

Do not request or log the DB password.

### Heavy AI

A separate V100 32 GB VM exists for future AI ranking/inference. Core WohnWerk must remain functional without that VM. AI should be called over HTTP as an optional service.

---

## 4. Database state

PostgreSQL:

- host: `10.169.2.6`
- PostgreSQL 15.16 (Debian 12)
- PostGIS 3.3.2
- database: `wohnwerk`
- owner/user: `shore-keeper`
- UTF-8
- PostGIS extension enabled

Applied migrations:

- `0001_initial`
- `0002_postal_centroid_metadata`
- `0003_crawl_coverage`

Important tables:

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
- `alembic_version`

Canonical properties and source listings are intentionally separate.

### Property model

Canonical `Property` currently carries:

- title
- description
- price
- living area
- plot area
- PLZ
- city
- approximate PLZ location
- active/inactive lifecycle

`PropertyListing` carries source provenance, source listing ID, URL, raw payload, lifecycle, and crawl-run sighting state.

### Job model

Foundation already exists for:

- title
- company
- description
- salary fields
- `job_fit_score`
- lifecycle
- multiple locations

The live job acquisition runner/source is the next major work item.

---

## 5. Austrian postal/geospatial data

Official RTR postal-code import is implemented.

RTR endpoint:

```text
https://data.rtr.at/api/v1/tables/plz.json?size=0
```

Filter addressable rows with `adressierbar == "Ja"`.

BEV address-register centroid enrichment is implemented from `ADRESSE.csv` using:

- `PLZ`
- `RW`
- `HW`
- `EPSG`
- EPSG 31254 / 31255 / 31256
- `pyproj`
- address-weighted mean per PLZ

Metadata constants:

```python
BEV_LOCATION_SOURCE = "BEV Adressregister Stichtagsdaten"
BEV_LOCATION_METHOD = "address_mean"
```

Production import already succeeded.

---

## 6. Property acquisition — current authoritative state

### 6.1 IMMMO.at — nationwide anchor

Role: Austrian real-estate meta-search discovery source.

Adapter path used by live runner:

```text
app.sources.property.immmo_v3.ImmmoPropertySource
```

Sharding: all 9 Bundesländer.

Bundesländer:

- Burgenland
- Kärnten
- Niederösterreich
- Oberösterreich
- Salzburg
- Steiermark
- Tirol
- Vorarlberg
- Wien

#### Authoritative successful run

**Run #11** was reclassified only after persisted diagnostics proved the crawl complete.

Current authoritative status:

```text
immmo.at [property] enabled coverage=ok
latest_run=11 mode=reconciliation status=success coverage=ok
seen=13948
new=13514
updated=434
disappeared=0
pages=1167
shards=9/9
cap_hits=0
```

Per-shard final counts:

| Shard | Pages | Seen | Synthetic |
| --- | ---: | ---: | ---: |
| Burgenland | 88 | 1049 | 33 |
| Kärnten | 96 | 1145 | 39 |
| Niederösterreich | 365 | 4379 | 106 |
| Oberösterreich | 152 | 1813 | 128 |
| Salzburg | 70 | 829 | 32 |
| Steiermark | 128 | 1529 | 102 |
| Tirol | 117 | 1399 | 41 |
| Vorarlberg | 36 | 427 | 29 |
| Wien | 115 | 1378 | 50 |

Total synthetic/linkless fallback records: **560 / 13,948 (~4.0%)**.

Important: synthetic URL quality is a separate metric from discovery completeness. All visible cards were materialized; synthetic records are marked with unstable identity semantics and are excluded from normal automatic deactivation.

#### Closed IMMMO problems — do not re-investigate from scratch

The following were already diagnosed and fixed:

- subtype headings such as `Einfamilienhaus kaufen in ...`
- result headings not always literally `Haus kaufen in ...`
- wrapped/card-wide external links
- cards with no recoverable original external URL
- visible pagination window being mistaken for the end of the catalog
- count drift during a long crawl
- failure diagnostics previously reporting `pages=0` after a late-page error
- partial shard work being discarded after a later page failure
- sparse updates erasing known metadata
- synthetic-link quality incorrectly blocking otherwise complete coverage

Current model is count-driven full traversal with strict card materialization and conservative lifecycle handling.

### 6.2 s REAL — independent direct source

Role: direct Austrian broker source, independent from IMMMO in the current snapshot.

Live runner uses:

```text
app.sources.property.sreal_v2.SRealPropertySource
```

Search URL:

```text
https://www.sreal.at/de/haeuser-kauf/angebot/10
```

#### Authoritative successful run

**Run #16**:

```text
status=success coverage=ok
shards=1/1 failed=0 pages=16
seen=314 new=6 updated=308
source_reported=None
disappeared=0
```

Diagnostics:

```text
cards=314
parsed=314
max_page=16
raw_anchors=314
duplicate_anchors=0
metadata_fallbacks=6
```

The six fallback records are real unique provider listing IDs whose search cards lacked metadata required by the older parser. `sreal_v2` correctly treats provider-issued detail identity as discovery truth and search-card area/price as enrichment.

#### Detail enrichment

After Run #16, targeted enrichment was run only for records missing detail metadata:

```text
missing_detail_enrichment=6
detail_enrichment_succeeded=6 failed=0
```

Current final s REAL data state:

```text
sreal_listings=314
detail_enriched=314
```

Detail enrichment captures available direct-source metadata such as:

- full object description
- purchase price
- Wohnfläche
- Grundfläche
- PLZ/city

Detail enrichment is best-effort and is not itself a discovery coverage gate.

#### Historical runs

- Run #12: failed because the first search parser did not handle live `m<sup>2</sup>` formatting.
- Run #13/#14: first-page discovery/enrichment validated.
- Run #15: full 16-page traversal found 308/314 because six sparse-metadata cards were not materialized. It remains historical degraded audit data.
- Run #16 supersedes Run #15 and is authoritative `coverage=ok`.

Do not reclassify Run #15. Run #16 is the correct baseline.

### 6.3 IMMMO ↔ s REAL overlap

Current diagnostics after full collection:

```text
immmo_sreal_exact_url_overlap=0
immmo_sreal_stable_id_overlap=0
already_merged=0
historical_duplicates=0
immmo_urls_pointing_to_sreal=0
```

Interpretation: the current IMMMO snapshot does not expose direct s REAL detail URLs. The 314 s REAL listings therefore provide independent coverage rather than merely duplicating IMMMO rows.

Stable-ID dedupe still exists and should remain: s REAL provider IDs embedded in `/de/immobilie/<id>/...` are deterministic identities if another source later exposes those URLs.

### 6.4 ImmoAds — retired/dead

`immoads.at` is disabled.

Historical run #1 remains for audit. Old indexed pages were stale and live routes redirected elsewhere; it is not a current independent source.

Do not revive it without new evidence that a legitimate current acquisition path exists.

---

## 7. Property deduplication rules

Current deterministic dedupe supports:

1. exact canonical URL equality; and
2. provider-specific stable external identity where unambiguous (currently s REAL object IDs).

Do **not** replace this with generic aggressive URL normalization or fuzzy merge logic in the ingestion path.

Future different-URL cross-source dedupe should be a separate scored/confidence layer using signals such as:

- PLZ
- price
- Wohnfläche
- Grundfläche
- normalized title
- description similarity

Do not auto-merge uncertain matches.

A historical repair utility exists for deterministic IMMMO/s REAL duplicates by exact s REAL object ID, but the current DB reports zero such duplicate groups.

---

## 8. Raw-payload enrichment semantics

Sparse discovery must not destroy detail metadata already stored in `PropertyListing.raw_payload`.

Important implemented rule:

- successful detail enrichment survives later search-only scans;
- a transient later detail failure must not downgrade a previous successful enrichment;
- old enrichment error fields are cleared on a later successful refresh.

The same enrichment-only principle applies to canonical property fields.

---

## 9. Useful operational commands

Environment:

```bash
cd /opt/wohnwerk
git checkout bootstrap/austria-mvp
git pull
source .venv/bin/activate
pip install -e '.[dev]'
```

Quality checks:

```bash
ruff check app migrations scripts tests
python -m compileall -q app migrations scripts
pytest -q
```

Source health:

```bash
python scripts/source_health.py
```

IMMMO full reconciliation when intentionally needed:

```bash
python scripts/run_immmo.py --reconcile --delay 0.45
```

Do not run this casually; it traverses roughly 1,167 pages at the current catalog size.

s REAL full discovery reconciliation:

```bash
python scripts/run_sreal.py --reconcile --delay 0.6
```

s REAL targeted detail enrichment:

```bash
python scripts/enrich_sreal_missing_details.py --delay 0.6
```

s REAL stats:

```bash
python scripts/sreal_run_stats.py
```

Cross-source overlap diagnostics:

```bash
python scripts/property_source_overlap.py
```

Deterministic s REAL duplicate repair, normally dry-run first:

```bash
python scripts/merge_sreal_stable_duplicates.py
python scripts/merge_sreal_stable_duplicates.py --apply
```

Current DB should report zero deterministic duplicate groups.

---

## 10. Source/legal research already done

### IMMMO

Current use is cautious, low-rate, private/self-hosted discovery. Re-review terms if deployment becomes public/commercial or usage model changes materially.

### IMMOunited

Current AGB explicitly prohibits automated/non-human retrieval, bots/scripts/crawling/scraping/caching/evaluation. Do not build a direct crawler without separate authorization.

### willhaben

Terms prohibit automated robot/crawler copying without consent. Do not use anti-bot evasion.

### ImmoScout24 Austria

Terms prohibit automated scripts/bots/crawlers/data extraction without written permission. Do not evade.

### Immowelt

An official API/WebService exists and is a future candidate if access/API key can be obtained.

### OpenImmo / Justimmo

OpenImmo is a feed standard rather than a global public API. Generic OpenImmo XML/ZIP import exists for feeds explicitly supplied/authorized. Justimmo has API/feed paths that require appropriate broker/partner access.

---

## 11. Job acquisition — NEXT MAJOR BLOCK

Property acquisition is sufficiently validated for the MVP. Do not spend the next development block endlessly polishing real-estate portals.

The next major milestone is **Austria-wide job ingestion** using the same coverage-first architecture.

### Preferred source strategy

Strong first anchor candidate: **AMS `alle jobs`** because it aggregates:

- AMS vacancies
- eJob-Room
- internet jobs from Austrian organizations
- public administration
- selected Germany/Italy jobs

Additional source pool to evaluate independently:

- karriere.at
- StepStone Austria
- jobs.at
- hokify
- Indeed Austria
- LinkedIn Jobs
- willhaben Jobs
- company career pages
- agencies/public-sector portals

Do source-by-source terms/API research before implementing acquisition.

### Mechanical-engineering query expansion

Initial recall-oriented role vocabulary:

- Maschinenbauingenieur
- Konstruktionsingenieur
- Entwicklungsingenieur
- Mechanical Engineer
- Mechanical Design Engineer
- Projektleiter Maschinenbau
- CAD-Konstrukteur
- Berechnungsingenieur
- Produktentwickler
- Sondermaschinenbau
- Application Engineer
- CAD
- Creo
- Blechkonstruktion
- Konstruktion
- Produktentwicklung

This query vocabulary is not the final fit model; it is a discovery expansion set.

### Job salary modeling rule

Do not blindly normalize monthly salary by multiplying by 14.

Preserve original salary dimensions and provenance:

- min/max
- currency
- period
- annualization/payment count only when explicit
- provenance: EXPLICIT / ESTIMATED / UNKNOWN
- confidence
- KV/legal minimum where applicable

Unknown salary should be neutral for job-fit scoring rather than treated as zero/bad.

### Job fit

Planned intrinsic fit score: 0–100.

Keep geographic distance separate from intrinsic job fit. Later, embeddings/light classifier can be trained once labeled examples exist.

---

## 12. Immediate continuation plan

When resuming from this checkpoint:

1. Read `HANDOFF.md` completely.
2. Run `python scripts/source_health.py` to confirm live acquisition state has not regressed.
3. Run test/lint suite before new changes.
4. Do **not** re-open IMMMO/s REAL parser debugging unless health or current live evidence shows a new regression.
5. Implement the generic **job ingestion runner/coverage path** by mirroring the proven property runner semantics rather than inventing a separate lifecycle model.
6. Research and implement the first legitimate high-recall Austrian job source, preferably AMS `alle jobs` if a permissible acquisition route is available.
7. Normalize job locations through Austrian PLZ and connect them to existing PostGIS matching helpers.
8. Then add a second independent job source and overlap/dedupe diagnostics.
9. Only after job acquisition is useful, move to web UI / matching workflows / user criteria.

---

## 13. Known minor housekeeping item at checkpoint

The latest local quality run reported:

```text
I001 Import block is un-sorted or un-formatted
```

while the test suite passed:

```text
39 passed, 1 warning
```

This is a formatting-only Ruff issue, not a functional failure. Resolve with the exact Ruff diagnostic or `ruff check --fix` before considering the branch fully lint-clean. Do not confuse this minor lint item with acquisition correctness.

---

## 14. Current milestone definition

**Property acquisition MVP milestone: achieved.**

Validated authoritative sources:

```text
IMMMO.at
  coverage=OK
  13,948 listings
  1,167 pages
  9/9 Bundesländer

s REAL
  coverage=OK
  314 listings
  16 pages
  314/314 detail-enriched

ImmoAds
  disabled / retired
```

The project should now move forward to **jobs**, not loop indefinitely on already-validated property acquisition.
