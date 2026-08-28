# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-28 (Europe/Berlin)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This is the authoritative recovery point for a fresh context.

## Product invariants

WohnWerk is a private/self-hosted Austria-first property + job acquisition, personalization and matching system.

- User/admin UI is German-only.
- `JobListing.status` is source lifecycle only.
- Discovery relevance stays in `raw_payload["wohnwerk_discovery_gate"]`.
- Candidate preferences/fit are independent and recomputable.
- Failed/partial frontier crawls never mass-deactivate.
- Do not invent Austrian PLZ/location coordinates; preserve provenance.
- Geography remains separate from intrinsic fit.
- No CAPTCHA bypass, credential theft, fingerprint spoofing or deliberate anti-bot evasion.

## Stable acquisition

Properties:
- IMMMO #11: 13,948 seen, coverage OK, 9/9 shards.
- s REAL #16: 314 seen, coverage OK, detail-enriched.
- ImmoAds disabled.

Jobs:
- SmartRecruiters #33: 42 relevant-active canonical jobs.
- Personio #37: 17 relevant-active jobs.
- Lever #22: 6 relevant jobs.
- karriere.at #40: 30 relevant jobs.
- jobs.at #41: 13 relevant jobs.
- StepStone #45: 37 relevant jobs, exactly 5 search requests, zero details.
- willhaben #46: 18 relevant jobs, exactly 5 requests, zero details.

Acquisition micro-polishing is intentionally paused.

## Discovery / dedupe — closed

Discovery gate: `profile-seed-2026-08-28-v14`.

Candidate direction is mechanical/Maschinenbau + technical project work. Pure electrical/electronics is `cannot + not want`; this affects candidate fit, not acquisition relevance.

Seven fail-closed canonical merges reduced the relevant corpus from 163 to 156 jobs, with 7 multi-listing canonicals. Final dedupe audit: high=0, blocked=1 (teampool Wien/Wels), medium=6. Do not reopen without stronger evidence.

## Normalized job concepts — production established

Migration `0007_job_concepts` is applied.

Current/persisted extractor: `concept-seed-2026-08-28-v3`.

Production state:
- relevant jobs: 156
- jobs with concepts: 156
- concepts matched: 50
- persisted evidence: 780 rows
- primary/context: 228 / 552
- only v3 deterministic evidence persisted
- `domain:electronics`: 27 jobs, 6 primary / 24 context
- `domain:electrical-engineering`: 40 jobs, 7 primary / 38 context

Evidence semantics: title=primary/1.00; description role=.45 context, domain=.55, task=.80, method/tool=.85.

Important guards: generic `Konstrukteur` does not imply mechanical domain; EPLAN alone does not imply electrical; FEM cannot match `female`; DB-enabled aliases drive applied extraction; deterministic recompute replaces only `concept-seed-*` evidence.

Normalization tuning is closed unless real ranking feedback demonstrates a generic semantic failure.

## Candidate profile + intrinsic fit — production established

Migration `0008_candidate_preferences` is applied.

Persisted profile:
- slug `mechanical-project-engineer`
- label `Maschinenbau / technische Projektleitung`
- seed `candidate-profile-2026-08-28-v2`
- 24 bootstrap preferences: 22 `can_want`, 2 `cannot_not_want`
- provenance `source=seed|manual` plus nullable `seed_version`
- seed sync never overwrites manual rows

Current policy: `candidate-fit-2026-08-28-v3`.

Core semantics:
- state values: +1.00 / -0.20 / +0.20 / -1.00
- kind weights: role 1.15, domain 1.25, task 1.00, method/tool .75
- scope weights: primary 1.00, context .35
- positive evidence budget 3.0
- primary role/domain `cannot_not_want` => explicit hard constraint, score cap 25
- context-only incompatibility is attenuated and never hard

DB-backed production audit:
- 156 relevant
- 141 scored / 15 unscored
- 13 hard-incompatible
- mean 61.14 / median 63.00
- coverage mean .586 / median .521
- mechanical top stable (#144=100, #131=95, #251=94)
- context-only controls #80/#82 remain non-hard at 32

`Job.job_fit_score` is **not** source of truth. For the current corpus, live recomputation from persisted profile/evidence is intentionally preferred over materializing a stale cache.

## German admin UI — production smoke-tested

Protected surfaces:
- `/admin/concepts`
- `/admin/jobs`

`/admin/concepts` is confirmed working against the production DB. It shows canonical concepts, aliases, current-extractor evidence counts, and all four can/want states. Preference POST uses normal POST→303→GET semantics. Explicit writes become `source=manual`; reset restores seed state or removes an unseeded manual rating. Alias add/enable/disable/manual-delete is supported. Alias changes intentionally require explicit normalization before they affect persisted evidence.

Security:
- fail-closed without `WOHNWERK_ADMIN_PASSWORD`
- Basic auth username defaults to `admin`
- byte-safe credential comparison
- HMAC CSRF on every write form
- packaged server-rendered Jinja templates

`/admin/jobs` is now implemented as a **live DB-backed ranking** rather than using `Job.job_fit_score`:
- default view shows scored, non-hard-compatible jobs
- filters: `Passend / Alle / Unvereinbar / Unbewertet`
- search by title/company/location
- score + preference coverage
- hard incompatibility labels
- top German concept drivers
- source-backed annual salary when available
- locations
- active source links
- navigation between Stellen and Konzepte

The ranking service is reusable in `app/jobs/fit_store.py` and recomputes from persisted v3 evidence + persisted candidate profile on each request, so manual preference edits are immediately reflected.

CI #476 passed Ruff, Compile and full tests for the live ranking slice.

## Network / runtime

Production LXC address: `10.169.0.150/24`.

Public hostname works through existing wildcard/DDNS DNS:
- `wohnwerk.kotaru.lainlounge.org`
- CNAME ultimately points to `kotaru.dyn.lainlounge.org`

Caddy is installed in the same LXC and HTTPS reverse proxy is confirmed working. Intended topology:

`HTTPS -> Caddy :443 -> 127.0.0.1:8000 -> WohnWerk`

A hardened systemd unit is now tracked at `deploy/wohnwerk.service`:
- runs as `www-data`
- binds Uvicorn only to `127.0.0.1:8000`
- trusts proxy headers only from localhost
- loads `/opt/wohnwerk/.env`
- restart-on-failure
- basic systemd hardening

CI #477 passed Ruff, Compile and full tests on the code + unit-file head.

## Immediate next steps

1. Pull latest branch and inspect `/admin/jobs` against the real production corpus.
2. Install/enable `deploy/wohnwerk.service` so backend survives LXC reboot alongside Caddy.
3. Once live ranking looks sane, implement the PostGIS distance engine between canonical jobs and properties without precomputing a permanent NxM matrix.
4. Add final recommendation composition from intrinsic fit + distance/commute + salary + property attributes.
5. Only introduce fit materialization/versioning if corpus size or UI latency demonstrates an actual need.
