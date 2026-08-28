# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-28 (Europe/Berlin)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This file is the authoritative recovery point for continuing WohnWerk in a fresh context.

## Product invariants

WohnWerk is a private/self-hosted Austria-first property + job acquisition, personalization and matching system.

- User/admin UI is German-only.
- `JobListing.status` is source lifecycle only.
- Professional discovery relevance stays in `raw_payload["wohnwerk_discovery_gate"]`.
- Candidate preferences and fit are independent/recomputable.
- Failed or partial frontier crawls never mass-deactivate.
- Do not invent Austrian PLZ/location coordinates; preserve provenance.
- Geography is separate from intrinsic candidate fit.
- No CAPTCHA bypass, credential theft, fingerprint spoofing or deliberate anti-bot evasion.

## Stable acquisition

Properties:
- IMMMO #11: coverage OK, 13,948 seen, 1,167 pages, 9/9 shards.
- s REAL #16: coverage OK, 314 seen, detail-enriched.
- ImmoAds disabled.

Jobs:
- SmartRecruiters #33: 42 relevant-active canonical jobs.
- Personio #37: 17 relevant-active jobs.
- Lever #22: 6 relevant jobs.
- karriere.at #40: 30 relevant jobs, 35 requests.
- jobs.at #41: 13 relevant jobs, 18 requests.
- StepStone #45: 37 relevant jobs, exactly 5 requests, zero details.
- willhaben #46: 18 relevant jobs, exactly 5 requests, zero details.

Acquisition micro-polishing is intentionally paused.

## Discovery gate

Current discovery gate: `profile-seed-2026-08-28-v14`.

Candidate direction: mechanical/Maschinenbau and technical project work; pure electrical/electronics is `cannot + not want`. Candidate preference must never be folded back into broad acquisition relevance.

## Canonical job dedupe — closed

Seven explicit fail-closed merges reduced the relevant canonical corpus from 163 to 156 jobs and created 7 multi-listing canonical jobs.

Final production audit:
- high duplicate candidates: 0
- blocked: 1 (teampool Wien/Wels location conflict)
- medium: 6

Do not reopen dedupe without stronger evidence.

## Job concepts — production established

Migration `0007_job_concepts` is applied.

Current/persisted extractor: `concept-seed-2026-08-28-v3`.

Production state:
- relevant jobs: 156
- jobs with concepts: 156
- concepts matched: 50
- persisted evidence rows: 780
- primary/context: 228 / 552
- only v3 deterministic evidence persisted
- `domain:electronics`: 27 jobs, 6 primary / 24 context
- `domain:electrical-engineering`: 40 jobs, 7 primary / 38 context

Evidence semantics:
- title -> primary / 1.00
- description role -> context / 0.45
- description domain -> context / 0.55
- description task -> context / 0.80
- description method/tool -> context / 0.85

Important guards:
- generic `Konstrukteur` does not imply mechanical domain;
- EPLAN alone does not imply electrical domain;
- FEM does not substring-match `female`;
- deterministic recompute replaces only prior `concept-seed-*` evidence;
- DB-enabled aliases drive applied extraction.

V3 intentionally added explicit electronics/electrical identity only where live ranking exposed gaps (`Elektronik`, `Electronics`, Hardware Engineer/Design, E-Konstrukteur, EMC/EMV, etc.).

Normalization tuning is closed unless real ranking feedback demonstrates a generic semantic failure.

## Candidate profile + fit — production established

Migration `0008_candidate_preferences` is applied in production.

Persisted profile:
- slug: `mechanical-project-engineer`
- label: `Maschinenbau / technische Projektleitung`
- seed version: `candidate-profile-2026-08-28-v2`
- preferences: 24
- source counts initially: `seed:24`
- states initially: `can_want:22`, `cannot_not_want:2`
- no missing/mismatched/stale/manual rows at bootstrap

Preference provenance:
- `source=seed|manual`
- nullable `seed_version`
- seed sync updates only seed-managed rows
- manual rows survive later seed sync

Current fit policy: `candidate-fit-2026-08-28-v3`.

Policy:
- states: can+want +1.00, can+not-want -0.20, cannot+want +0.20, cannot+not-want -1.00
- kind weights: role 1.15, domain 1.25, task 1.00, method/tool 0.75
- scope weights: primary 1.00, context 0.35
- positive evidence budget: 3.0
- primary role/domain `cannot_not_want` => explicit hard constraint and score cap 25
- context-only incompatibility is attenuated and never hard

DB-backed production fit audit exactly matches the accepted preview:
- relevant jobs: 156
- scored/unscored: 141 / 15
- hard-incompatible: 13
- mean/median: 61.14 / 63.00
- coverage mean/median: 0.586 / 0.521

Mechanical top remains stable (#144=100, #131=95, #251=94). Explicit primary electrical/electronics jobs are hard-incompatible and <=25; #128/#213 naturally score 0. Context-only controls #80/#82 remain non-hard at 32.

`Job.job_fit_score` is still not the source of truth. Do not blindly write it until materialization semantics/versioning are chosen.

## German admin UI — code ready, not yet smoke-tested in production

New files/surfaces:
- `app/admin.py`
- `app/jobs/admin_store.py`
- `app/templates/admin_concepts.html`
- `tests/test_admin_concepts.py`
- `/admin/concepts`

Features:
- server-rendered German Jinja UI, no frontend framework/JS dependency;
- filters for Rolle/Fachgebiet/Aufgabe/Methode/Werkzeug;
- canonical concept label/slug;
- current-extractor job/primary/context evidence counts;
- four candidate states;
- provenance display: Standard / Manuell / Unbewertet;
- any explicit state write becomes `source=manual` and clears `seed_version`;
- reset restores the seed state for seeded concepts or removes an unseeded manual rating;
- aliases are visible with enabled/disabled state;
- add manual alias;
- enable/disable aliases;
- delete manual aliases only; seed aliases can be disabled but not deleted.

Alias edits intentionally do **not** mutate persisted evidence automatically. UI shows a notice that normalization must be re-run before the changed aliases affect fit.

Security:
- `/admin` is fail-closed until `WOHNWERK_ADMIN_PASSWORD` is configured;
- username defaults to `admin`, configurable by `WOHNWERK_ADMIN_USERNAME`;
- HTTP Basic authentication;
- byte-safe credential comparison (supports non-ASCII passwords);
- HMAC CSRF token on every write form;
- Jinja template is included in package data.

CI #470 passed Ruff, Compile and the complete test suite including admin HTTP/service lifecycle and CSRF path.

## Immediate next steps

1. Pull latest `bootstrap/austria-mvp`.
2. Configure `WOHNWERK_ADMIN_PASSWORD` in `.env` without printing it to logs/history.
3. Start/restart the FastAPI service and open `/admin/concepts`.
4. Smoke-test one preference change and reset; verify DB-backed `candidate_fit_audit.py --persisted-profile` changes and returns to baseline as expected.
5. Smoke-test alias add/disable/delete. After alias changes, explicitly run `normalize_job_concepts.py --apply` plus persisted concept/fit audits before trusting the changed taxonomy.
6. Once UI behavior is confirmed, decide materialized-fit semantics/versioning instead of treating `Job.job_fit_score` as source of truth.
7. Then implement intrinsic-fit display/ranking surfaces and combine with PostGIS job/property distance + salary for final recommendations.

Current code before this documentation checkpoint: admin UI/security commit series ending at `084106c` with CI #470 green.
