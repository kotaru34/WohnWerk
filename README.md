# WohnWerk

WohnWerk is a private, self-hosted home-and-job matching system for Austria.

Its purpose is to reduce a large manual search problem to one local interface:

- collect houses for sale from multiple Austrian sources;
- collect and normalize relevant job vacancies from multiple Austrian sources;
- keep source records and historical state locally;
- score jobs against a manually curated professional profile;
- match homes and jobs dynamically by configurable geographic radius;
- provide an intuitive web UI for browsing in both directions: **home -> nearby jobs** and **job -> nearby homes**.

## Current status

The Austria-first data foundation is live:

- PostgreSQL 15 + PostGIS database deployed;
- Austrian PLZ data imported from RTR;
- BEV address data reduced to PLZ centroid geography;
- PostGIS radius matching ready;
- source adapter contracts implemented;
- coverage-first crawl model implemented with source shards, crawl runs and reconciliation safety;
- generic OpenImmo XML/ZIP full-feed property adapter implemented;
- CI covers application code, migrations, operational scripts and tests.

The next milestone is to connect real Austrian property sources through complete/authorized feeds, APIs, regional portals and direct broker sources, then bring the same coverage model to jobs.

## Design principles

- Austria-first, multi-source by design.
- Coverage is measured, not assumed.
- Saved-search alerts are supplemental and never treated as authoritative inventory.
- Search spaces are sharded when pagination/result caps prevent full traversal.
- Incomplete reconciliation is never allowed to mass-deactivate listings.
- Source adapters may use an official API, complete feed, static HTTP acquisition, or normal browser automation depending on the source.
- Conservative, source-specific external request rates.
- Raw source data is retained so parsers and enrichment can be rerun locally.
- Canonical entities are separated from source listings to support deduplication.
- Houses and jobs are stored independently; geographic pairing is computed dynamically.
- `job_fit_score` is separate from any home/job pair score.
- AI enrichment is optional and isolated behind an internal API; the core application must continue working without the AI VM.
- Approximate postal-code geography is sufficient for the intended 25/50/100/custom km matching workflow.

## Stack

- Python
- FastAPI
- PostgreSQL + PostGIS
- SQLAlchemy / GeoAlchemy
- Alembic
- HTMX + server-rendered templates for the first UI
- Playwright where browser automation is appropriate
- Optional embedding / LLM enrichment through a separate GPU VM

Detailed architecture, acquisition strategy, requirements and source research live under `docs/`.
