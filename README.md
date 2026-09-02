# WohnWerk

Private/self-hosted Austrian and German house + job acquisition, personalization and matching application.

## Active development

- Frozen Austria baseline: `release/v1-austria`
- Germany-oriented MVP: `feature/germany`
- Authoritative operational checkpoint: `HANDOFF.md`
- Germany product/UI/acquisition contract: `docs/germany_mvp.md`

Fresh contexts should read `HANDOFF.md` first and then `docs/germany_mvp.md` before making changes.

## Documentation

- `docs/germany_mvp.md` — Germany MVP goal, DE/AT UX, acquisition/legal guardrails and rollout gate
- `docs/acquisition.md` — coverage, sharding, incremental and reconciliation model
- `docs/sources.md` — source inventory and source-specific acquisition policies
- `docs/requirements.md` — broader product requirements; older sections remain Austria-first where Germany-specific rules are not yet folded in
- `docs/architecture.md` — architecture notes
- `docs/job_matching_model.md` — job scoring/matching model
- `docs/professional_seed.md` — candidate professional seed

## Core runtime

- FastAPI / Uvicorn
- PostgreSQL + PostGIS
- server-rendered German UI
- country-scoped `Häuser`, `Jobs`, and `Matching`
- deterministic core operation without requiring AI

Germany commercial property portal acquisition is deliberately minimal-retention and public-only; see `docs/germany_mvp.md` before changing those adapters.
