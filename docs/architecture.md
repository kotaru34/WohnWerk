# WohnWerk Architecture

Status: bootstrap design, Austria-first

## Goal

WohnWerk continuously builds a local, normalized knowledge base of Austrian houses for sale and Austrian job vacancies, then lets the user browse and match the two datasets in either direction.

The core system must remain usable even if individual external sources or the optional AI VM are unavailable.

## High-level components

```text
Austrian property sources       Austrian job sources
          |                              |
          +---------- source adapters ---+
                         |
                    raw ingestion
                         |
                     normalizer
                         |
                PostgreSQL + PostGIS
                  /              \
          canonical homes     canonical jobs
                  \              /
                   dynamic geo matching
                         |
                    scoring layer
                         |
                     FastAPI/UI
                         |
                      browser

Optional enrichment path:
normalized job -> enrichment queue -> internal AI VM API -> structured features / embeddings
```

## Core decisions

### Austria-first

The initial implementation supports Austria only. Austrian postal codes are four digits and are the primary location key when exact addresses are unavailable or unnecessary.

### Multi-source from day one

Every external website or feed is isolated behind a source adapter. The application does not care whether an adapter uses:

1. an official/public API;
2. a feed or structured endpoint;
3. static HTTP parsing;
4. Playwright/browser automation.

Acquisition is source-specific. Polling frequency, request pacing, pagination limits, and active-status checks belong to the adapter/configuration rather than global crawler behavior.

Browser automation may reproduce ordinary user-facing navigation where appropriate, but the project does not depend on bypassing CAPTCHAs, access controls, or other protective measures.

### Canonical entities are separate from source listings

A house or job may appear on several portals. We store one canonical entity and attach multiple source listings to it.

This enables deduplication while preserving provenance, source URLs, source IDs, first/last seen timestamps, and source-specific raw data.

### Preserve raw source data

Normalized fields are not the only retained representation. Raw structured payloads/snapshots are kept where practical so parser fixes and improved AI extraction can be rerun locally without fetching the same source page again.

### Houses and jobs remain independent

No giant precomputed house x job relationship table is required.

A user selecting a house and a radius triggers a PostGIS query for nearby job locations. Selecting a job triggers the inverse query for houses.

PostGIS `geography` points are used so `ST_DWithin` distances are expressed in metres.

### Postal-code accuracy is enough

For this use case, a PLZ centroid is sufficient. Exact street-level coordinates are optional enrichment, not a requirement.

Location confidence should remain explicit so approximate postal-code geography is never presented as exact coordinates.

### Jobs may have several locations

One canonical vacancy may be valid for several Austrian cities/regions. Job locations therefore live in a separate `job_locations` table. Radius matching can use the closest valid location.

### Separate scores

`job_fit_score` represents professional suitability independent of any house.

A future `pair_score` may combine job fit, geographic distance, and other pair-specific preferences for a selected house/job pair.

Do not make geographic distance mutate the canonical job-fit score.

### AI is optional infrastructure

The GPU is passed through to a separate VM. WohnWerk communicates with it over an internal HTTP API.

Potential AI endpoints:

```text
POST /embed
POST /analyze-job
```

The application should queue enrichment work and mark it pending when the AI VM is unavailable. Ingestion, deterministic scoring, geographic matching, and the web UI must continue functioning.

### Salary handling is Austria-specific

Austrian job advertisements generally expose a minimum remuneration basis, which is useful for ranking, but advertisements often describe a collective-agreement minimum rather than the actual offer.

Store both raw salary text and normalized values with provenance/confidence.

Do not blindly convert every monthly figure to annual salary by multiplying by 14. Holiday/Christmas special payments (often called the 13th/14th salary) depend on the applicable collective agreement or employment contract and are not a universal statutory entitlement.

## Initial deployment model

```text
PVE host
|
|-- WohnWerk app/container
|     |-- FastAPI
|     |-- source adapters
|     |-- scheduler/worker
|     `-- server-rendered UI
|
|-- existing PostgreSQL container
|     `-- PostGIS extension (to be added)
|
`-- GPU VM (existing V100 passthrough)
      `-- optional embeddings / Qwen analysis API
```

The existing PostgreSQL service remains the system of record. The deployment work must install compatible PostGIS packages in that PostgreSQL image/container before `CREATE EXTENSION postgis` is executed.

## MVP boundary

The first useful version is intentionally small:

1. PostgreSQL/PostGIS schema;
2. Austrian PLZ reference import + centroid coordinates;
3. one real Austrian property source;
4. one real Austrian job source;
5. deterministic property filters;
6. basic deterministic job relevance;
7. house -> jobs radius query;
8. job -> houses radius query;
9. minimal local web UI;
10. original source links and active/inactive status.

Only after this path works end-to-end do we expand source coverage, skill taxonomy, semantic embeddings, feedback learning, maps, and richer scoring.
