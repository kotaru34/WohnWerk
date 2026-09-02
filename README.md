# WohnWerk

Austria-first, self-hosted property + job acquisition and recommendation system.

Current architecture keeps source lifecycle, canonical identity, normalized professional concepts, candidate preference/fit and geography as separate layers.

## Current production state

- Properties: IMMMO + s REAL.
- Jobs: supplementary ATS feeds plus low-impact Austrian broad-board frontiers.
- Canonical job corpus: 156 relevant jobs after reviewed fail-closed dedupe.
- Normalized job concepts: migration `0007_job_concepts` applied; 747 deterministic evidence rows across 156 jobs.
- Evidence distinguishes title `primary` identity from description `context`.

## Current development stage

Candidate concept preferences use four states:

- `can_want`
- `can_not_want`
- `cannot_want`
- `cannot_not_want`

The current fit engine is versioned and read-only. Do not apply migration `0008_candidate_preferences` until the production ranking audit has been reviewed.

Run:

```bash
python scripts/candidate_fit_audit.py --limit 25
```

For detailed contribution inspection:

```bash
python scripts/candidate_fit_audit.py --job-id <JOB_ID>
```

`HANDOFF.md` is the authoritative detailed checkpoint and work order.
