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

## Candidate profile + intrinsic fit — father-reviewed baseline

Migration `0008_candidate_preferences` is applied. Profile slug `mechanical-project-engineer`, label `Maschinenbau / technische Projektleitung`.

Fit policy remains `candidate-fit-2026-08-28-v3` with primary/context semantics, positive evidence budget 3.0 and primary role/domain `cannot_not_want` hard constraint capped at score 25. `Job.job_fit_score` is not source of truth; current UI recomputes live from persisted profile + persisted concept evidence.

Historical bootstrap validation was 141 scored / 15 unscored / 13 hard-incompatible, mean 61.14 / median 63. Do not use that as the current target.

On 2026-08-28 the real candidate/father reviewed the concept set in production. Current read-only persisted-profile audit:
- persisted preferences: 50
- source counts: manual 27 / seed 23
- states: can_want 34 / cannot_not_want 10 / cannot_want 6
- scored: 155 / unscored: 1
- hard-incompatible: 38
- score mean: 56.79
- score median: 62.00
- preference coverage mean: 0.974
- preference coverage median: 1.000

Current top includes #205, #214 and #223 at 100; #144=96; #251=94; #136=92. Service/building-services/electrical/electronics roles correctly move into the hard-incompatible tail according to the father-reviewed profile.

The 27 manual / 23 seed split is intentional UI provenance: only explicit `source=manual` choices count as candidate-confirmed in the `Bewertet` review filter, although all persisted ratings still participate in scoring.

## Production UI / runtime

Public URL is live through Caddy HTTPS:
- `https://wohnwerk.kotaru.lainlounge.org`
- Caddy -> `127.0.0.1:8000`

`deploy/wohnwerk.service` is installed and working in production; backend survives reboot alongside Caddy.

Protected German admin surfaces:
- `/admin/concepts`
- `/admin/jobs`

Security: fail-closed Basic auth, configurable username, byte-safe password comparison, HMAC CSRF on every write form.

### Concepts

`/admin/concepts` has combined filters:
- type: Alle / Rolle / Fachgebiet / Aufgabe / Methode / Werkzeug
- review status: Alle / Bewertet / Unbewertet

Review semantics:
- `source=manual` = explicitly reviewed/confirmed by candidate -> Bewertet
- `source=seed` = bootstrap default, still not candidate-confirmed -> Unbewertet/open
- no row = Unbewertet/open

Reviewed cards are visually quieter; open cards get a subtle accent. Progress counts expose confirmed vs still-open concepts.

### Jobs

`/admin/jobs` labels the two metrics explicitly:
- **Passung N / 100** = intrinsic candidate/job fit
- **Bewertungsbasis N %** = normalized job evidence covered by rated profile concepts

Cards use restrained score-band/tint styling. Filters include Passend / Favoriten / Alle / Unvereinbar / Unbewertet / Ausgeblendet.

Migration `0009_candidate_job_preferences` supplies sparse per-profile `favorite` / `hidden` state. Hidden jobs remain recoverable; favorites are independent. Future canonical merge OR-preserves curation state onto the survivor before donor deletion. The user confirmed the current father-feedback UI version is working in production after deployment cleanup.

## PostGIS spatial matching — first read-only slice ready

Existing `Property.location` and `JobLocation.location` are `geography(POINT,4326)` with spatial indexes.

Current location semantics are approximate by design:
- properties receive resolved Austrian PLZ points from BEV-derived postal centroids
- job locations use explicit resolved PLZ centroids when available
- otherwise conservative locality centroids derived from RTR postal names + BEV postal centroids
- unresolved/countrywide locations remain ungeocoded; no coordinates are invented

New `app/matching.py` provides:
- `geo_coverage()` for production coverage diagnostics
- `nearest_properties_for_job_stmt()` / `nearest_properties_for_job()`
- `load_spatial_candidate_matches()` combining current live father-reviewed fit with on-demand spatial selection

Spatial query semantics:
- `ST_DWithin` constrains candidate pairs first so PostGIS can use spatial indexes
- exact geography `ST_Distance` returns straight-line geodesic distance
- multi-location jobs use a window to keep only the nearest job location per property
- no permanent Job×Property pair table is created
- hidden, hard-incompatible and unscored jobs are excluded before geography
- favorite is curation only and does not boost intrinsic score
- distance is explicitly **Luftlinie**, not road/travel time

Read-only CLI: `scripts/spatial_match_audit.py`.

CI #502 passed Ruff, Compile and the full test suite for the spatial service/audit slice.

## Immediate next steps

1. Pull current branch; no migration is required for the spatial slice.
2. Run `python scripts/spatial_match_audit.py --radius-km 50 --jobs 10 --properties-per-job 5` against production.
3. Inspect production geo coverage and actual nearest-house pairs. If coverage is healthy, treat centroid-level distance as the first geographic ranking signal.
4. Add a German matching UI surface and property source links/filters around the validated spatial service.
5. Compose final recommendation score from intrinsic fit + distance + source-backed salary + property price/area attributes.
6. Only add road routing/travel-time estimation after centroid-distance matching is validated; never label Luftlinie as commute time.
