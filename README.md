# WohnWerk

Self-hosted Austrian/German property acquisition and recommendation system with the proven Austrian job workflow.

The stable Austria-only release is frozen on `release/v1-austria`. Development on
`feature/germany` preserves the same matching, lifecycle and fail-closed coverage logic while
adding a `DE / AT` country scope.

Fresh development contexts should read `HANDOFF.md` first and then `docs/germany_mvp.md` before
making changes. `HANDOFF.md` is the authoritative operational checkpoint; `docs/germany_mvp.md`
records the Germany product/UI/acquisition contract and legal/operational guardrails.

## Market sources

- AT properties: `immmo.at`, `sreal.at`, plus configured OpenImmo feeds.
- DE properties: `immoscout24-de`, `immowelt-de`, plus configured OpenImmo feeds.
- DE jobs: currently paused; dormant adapters are not part of the automatic scheduler.
- Existing Austrian job and employer-ATS sources remain unchanged.

The German portal adapters retain only the source-backed data needed by WohnWerk and link back to
the original listing. Current Germany house acquisition/product target is EUR 30,000..200,000.
Immowelt requests ordinary `Buy` listings only; explicit auction evidence is retained but locally
rejected instead of being silently discarded. Incremental scans request the newest
pages; disappearance is accepted only after every applicable shard completes a full authoritative
scan below its safety cap.

## German data bootstrap

```bash
alembic upgrade head
python scripts/import_german_postal_codes.py
playwright install chromium
python scripts/run_immowelt_de.py
```

ImmoScout24 DE remains paused on the current production environment. Immowelt uses ordinary browser
rendering and persists a resumable checkpoint when it encounters a challenge. The external challenge
handler is operator-owned; WohnWerk owns only the integration boundary and does not modify the
handler implementation.

See also:

- `docs/germany_mvp.md` — Germany MVP goal, DE/AT UX, retention/access rules and rollout gate;
- `docs/acquisition.md` — sharding, incremental and reconciliation authority;
- `docs/sources.md` — source-specific acquisition policy and planning;
- `docs/requirements.md` — broader product requirements; older parts remain Austria-first where a
  Germany-specific rule has not yet been folded in.
