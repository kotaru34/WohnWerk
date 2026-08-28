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
- Candidate preferences, curation and fit are independent/recomputable.
- Failed/partial frontier crawls never mass-deactivate.
- Do not invent Austrian PLZ/location coordinates; preserve provenance.
- Geography remains separate from intrinsic fit.
- No CAPTCHA bypass, credential theft, fingerprint spoofing or deliberate anti-bot evasion.

## Stable acquisition / dedupe

Properties: IMMMO #11 = 13,948 coverage OK; s REAL #16 = 314 coverage OK/detail-enriched. ImmoAds disabled.

Jobs: SmartRecruiters #33=42, Personio #37=17, Lever #22=6, karriere.at #40=30, jobs.at #41=13, StepStone #45=37, willhaben #46=18 relevant jobs. Acquisition micro-polishing is intentionally paused.

Discovery gate remains `profile-seed-2026-08-28-v14`. Seven fail-closed canonical merges reduced the relevant corpus 163 -> 156 with 7 multi-listing canonicals. Final dedupe audit: high=0, blocked=1 (teampool Wien/Wels), medium=6. Do not reopen without stronger evidence.

## Job concepts — production established

Migration `0007_job_concepts` is applied. Persisted extractor `concept-seed-2026-08-28-v3`:
- 156/156 relevant jobs have concepts
- 50 concepts
- 780 evidence rows
- 228 primary / 552 context
- only v3 deterministic evidence persisted

Important guards remain: generic Konstrukteur does not imply mechanical domain; EPLAN alone does not imply electrical; FEM cannot substring-match `female`; DB-enabled aliases drive applied extraction.

Normalization tuning is closed unless real ranking feedback exposes a generic semantic failure.

## Candidate profile + intrinsic fit

Migration `0008_candidate_preferences` is applied. Profile slug `mechanical-project-engineer`, label `Maschinenbau / technische Projektleitung`.

Fit policy remains `candidate-fit-2026-08-28-v3` with primary/context semantics, positive evidence budget 3.0 and primary role/domain `cannot_not_want` hard constraint capped at score 25. `Job.job_fit_score` is not source of truth; current UI recomputes live from persisted profile + persisted concept evidence.

The old bootstrap validation baseline was 141 scored / 15 unscored / 13 hard-incompatible, mean 61.14 / median 63. This baseline is now **historical only**: on 2026-08-28 the candidate/father reviewed the concepts through the production UI, so persisted manual ratings are now the real source of truth and the ranking legitimately changed. Capture a new father-reviewed audit before geography composition; do not force results back to the old seed baseline.

## Production UI / runtime

Public URL is live through Caddy HTTPS:
- `https://wohnwerk.kotaru.lainlounge.org`
- Caddy -> `127.0.0.1:8000`

`deploy/wohnwerk.service` is installed and working in production; backend survives reboot alongside Caddy.

Protected German admin surfaces:
- `/admin/concepts`
- `/admin/jobs`

Security: fail-closed Basic auth, configurable username, byte-safe password comparison, HMAC CSRF on every write form.

## Father-reviewed UX slice — code ready, migration 0009 not yet production-applied

Real WIP testing with the candidate/father produced three UX requirements. All are implemented and covered by CI #497 (Ruff + Compile + 220 tests green).

### Concepts

`/admin/concepts` now has combined filters:
- type: Alle / Rolle / Fachgebiet / Aufgabe / Methode / Werkzeug
- review status: Alle / Bewertet / Unbewertet

Review semantics are deliberate:
- `source=manual` = explicitly reviewed/confirmed by candidate -> Bewertet
- `source=seed` = bootstrap default, still not candidate-confirmed -> Unbewertet/open
- no row = Unbewertet/open

Reviewed cards are visually quieter (~72% opacity, full on hover/focus). Open cards get a subtle accent border/background. Progress counts show candidate-confirmed vs still-open concepts. This prevents our historical seed assumptions from masquerading as father feedback.

### Job ranking clarity

`/admin/jobs` now labels the two numbers explicitly:
- **Passung N / 100** = intrinsic candidate/job fit
- **Bewertungsbasis N %** = how much of the job's normalized concept evidence is covered by rated profile concepts

The old ambiguous `Abdeckung` wording is removed.

Cards retain the minimalist dark design but gain only a subtle left score-band and faint tint for excellent/good/medium/low/hard/unrated categories.

### Favorite / hide

New candidate-specific curation state:
- `favorite`
- `hidden`

These flags are independent and belong to `(CandidateProfile, Job)`, never to source lifecycle.

New filters:
- Passend
- Favoriten
- Alle
- Unvereinbar
- Unbewertet
- Ausgeblendet

Hidden jobs disappear from normal views but remain in DB and are recoverable under Ausgeblendet. Favorites have their own view. Sparse curation rows are deleted when both flags return to false.

Migration `0009_candidate_job_preferences` creates `candidate_job_preferences`; it contains no automatic data changes and starts empty.

Future canonical merge safety is implemented in `candidate_job_store.merge_candidate_job_states()`: favorite/hidden are OR-preserved onto the merge survivor per candidate profile. The fail-closed `scripts/merge_duplicate_jobs.py --apply` uses this helper in the same transaction before deleting absorbed canonical jobs.

## Immediate production sequence

1. Pull current branch.
2. Apply `alembic upgrade head`; expected head becomes `0009_candidate_job_preferences`.
3. Restart `wohnwerk.service`.
4. Check `/admin/concepts`: if father explicitly clicked every concept, open count should be 0. Seed defaults that were never clicked correctly remain open.
5. Check `/admin/jobs`: verify Passung/Bewertungsbasis wording, subtle score bands, favorite, hide, Favoriten and Ausgeblendet views.
6. Run `python scripts/sync_candidate_profile.py` read-only and `python scripts/candidate_fit_audit.py --persisted-profile --limit 25` to capture the new father-reviewed profile/ranking baseline.
7. Once that new baseline is checkpointed, implement PostGIS job↔property distance queries without a permanent NxM matrix, then compose final recommendation ranking from intrinsic fit + commute/distance + salary + property attributes.
