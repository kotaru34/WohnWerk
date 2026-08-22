# WohnWerk

WohnWerk is a private, self-hosted home-and-job matching system for Austria.

Its purpose is to reduce a large manual search problem to one local interface:

- collect houses for sale from multiple Austrian sources;
- collect and normalize relevant job vacancies from multiple Austrian sources;
- keep source records and historical state locally;
- score jobs against a manually curated professional profile;
- match homes and jobs dynamically by configurable geographic radius;
- provide an intuitive web UI for browsing in both directions: **home -> nearby jobs** and **job -> nearby homes**.

## Project status

Early bootstrap / architecture phase.

The initial target is an Austria-first MVP that can:

1. ingest at least one real-estate source;
2. ingest at least one job source;
3. normalize both into PostgreSQL;
4. resolve Austrian postal codes to approximate locations;
5. perform radius matching with PostGIS;
6. expose filtered results through a local web UI.

## Design principles

- Austria-first, multi-source by design.
- Source adapters may use an official API, public feed, static HTTP parsing, or browser automation depending on the source.
- Conservative, source-specific polling rather than aggressive crawling.
- Raw source data is retained so parsers and enrichment can be rerun locally.
- Canonical entities are separated from source listings to support deduplication.
- Houses and jobs are stored independently; geographic pairing is computed dynamically.
- `job_fit_score` is separate from any home/job pair score.
- AI enrichment is optional and isolated behind an internal API; the core application must continue working without the AI VM.
- Approximate postal-code geography is sufficient for the intended 25/50/100/custom km matching workflow.

## Planned stack

- Python
- FastAPI
- PostgreSQL + PostGIS
- SQLAlchemy / GeoAlchemy
- Alembic
- HTMX + server-rendered templates for the first UI
- Playwright where browser automation is appropriate
- Optional embedding / LLM enrichment through a separate GPU VM

## Repository

Detailed architecture, requirements, source research, database schema, and deployment notes will live under `docs/` as implementation progresses.
