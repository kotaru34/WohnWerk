# WohnWerk

Self-hosted Austrian and German property + job acquisition and recommendation system.

The stable Austria-only release is frozen on `release/v1-austria`. Development on
`feature/germany` preserves the same matching, lifecycle and fail-closed coverage logic while
adding a `DE / AT` country scope.

## Market sources

- AT properties: `immmo.at`, `sreal.at`, plus configured OpenImmo feeds.
- DE properties: `immoscout24-de`, `immowelt-de`, plus configured OpenImmo feeds.
- DE jobs: Adzuna's documented Germany API and the public Bundesagentur Jobsuche interface.
- Existing Austrian job and employer-ATS sources remain unchanged.

The German portal adapters retain only title, price, living/plot area, PLZ, city and the original
listing URL. They do not copy descriptions, contact data or photos. Incremental scans request the
newest pages; disappearance is accepted only after every state/price shard completes a full scan
below its safety cap.

## German data bootstrap

```bash
alembic upgrade head
python scripts/import_german_postal_codes.py
playwright install chromium
python scripts/run_immoscout24_de.py
python scripts/run_immowelt_de.py
```

Run either property source with `--reconcile` only after its incremental smoke run is healthy.
Immowelt uses ordinary browser rendering and stops on an access challenge; there is no login,
stealth or CAPTCHA-solving path.

`HANDOFF.md` is the authoritative detailed checkpoint and rollout order.
