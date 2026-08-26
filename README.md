# WohnWerk

Self-hosted Austrian home and job discovery/matching system.

WohnWerk collects Austrian houses for sale and job vacancies from multiple independent sources, normalizes and deduplicates them, ranks jobs for candidate fit, and matches homes and jobs by geographic radius using PostgreSQL/PostGIS.

## MVP scope

- Austria only
- property and job discovery from source-specific adapters
- coverage-first crawling with explicit shard/reconciliation state
- Austrian PLZ reference data with PostGIS geography
- house -> nearby jobs and job -> nearby houses
- preserved source URLs and raw source payloads
- local LAN web UI
- optional external AI enrichment; core crawling and matching must work without AI

## Current live-data foundation

- RTR Austrian PLZ import
- BEV-derived PLZ centroids
- coverage-aware crawl runs and source shards
- generic OpenImmo full-feed property adapter
- ImmoAds.at Austrian house-for-sale adapter with incremental and full reconciliation modes
- operational source-health CLI

See `docs/architecture.md`, `docs/requirements.md`, and `docs/sources.md` for the current design.