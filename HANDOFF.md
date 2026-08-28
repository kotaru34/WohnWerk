# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-28 (Europe/Berlin)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`

This file is the authoritative recovery point for continuing WohnWerk in a fresh context.

## Product direction / invariants

WohnWerk is a private/self-hosted Austria-first house + job acquisition, personalization and matching system.

- End-user UI is German only.
- Never request or print DB/API credentials.
- `JobListing.status` is source lifecycle only.
- Professional relevance is independent in `raw_payload["wohnwerk_discovery_gate"]`.
- Candidate fit/preferences are independent and recomputable.
- Failed/partial frontier runs never mass-deactivate.
- Do not invent Austrian PLZ/location points; preserve source provenance.
- Geography is separate from intrinsic fit; use PostGIS rather than permanent NxM pairs.
- No CAPTCHA bypass, credential theft, fingerprint spoofing or deliberate anti-bot evasion.

## User-directed acquisition model

The user explicitly wants consumer-board acquisition to behave like a person quickly scanning vacancies:

- a handful of broad/focused searches;
- first result page initially;
- stable-ID dedupe;
- details only when actually useful and title looks interesting;
- sequential low-rate requests;
- no whole-site crawl, aggressive pagination or reconciliation for these frontiers;
- ToS text can inform priority but is advisory rather than an architecture blocker by itself;
- no technical anti-bot bypass.

Do not return to the earlier overcautious permission-first/purge detour. Adzuna/Jooble remain useful supplementary APIs, not replacements for normal boards.

## Stable property acquisition

Do not reopen absent live regression:

- IMMMO #11: coverage OK, 13,948 seen, 1,167 pages, 9/9 shards, disappeared=0.
- s REAL #16: coverage OK, 314 seen, detail-enriched, disappeared=0.
- ImmoAds retired/disabled.

## Stable supplementary ATS job sources

- SmartRecruiters #33: 15/15, coverage OK, 53 source-active / 42 relevant-active listings, 41/42 relevant locations resolved; liveness and republish identity closed.
- Personio #37: 14/14, 28 DE+EN feed requests, coverage OK, source_reported=215, 17 relevant-active jobs; only `österreichweit` unresolved.
- Lever #22: 5/5, coverage OK, 6 relevant active jobs, all relevant locations resolved.

Keep ATS feeds supplementary. Do not scale primarily by manually enumerating employers.

## Discovery gate v14 / candidate direction

Current gate: `profile-seed-2026-08-28-v14`. Generic discovery correctness is closed unless a genuinely generic bug appears.

Candidate is fundamentally mechanical/Maschinenbau, not electrical. Future fit should strongly prefer mechanical CAD/construction, components/assemblies, automotive/special-vehicle/rail work, product development, technical project work, supplier coordination and mechanically relevant validation/testing. Pure electrical engineering is explicit future fit `cannot + not want`; this must affect candidate fit, not broad acquisition.

## Stable low-impact broad boards

### karriere.at — production #40

- 5/5 shards, 35 HTTP requests;
- 30 relevant jobs;
- 34 relevant locations, 27 geo-resolved;
- 27 structured salaries, 15 annualized;
- no source/rate-limit errors.

Do not deepen traversal yet.

### jobs.at — production #41

Current broad searches: Maschinenbau, Konstrukteur, CAD Konstrukteur, Mechanischer Konstrukteur, SolidWorks.

- 5/5 shards, 18 HTTP requests;
- 13 relevant jobs;
- 14 relevant locations, 7 geo-resolved;
- 12 structured salaries + 1 salary text.

`E-Plan` roles may remain in broad acquisition and later rank down via candidate fit.

### StepStone Austria — clean production #45

Design: five search pages, zero details, stable numeric listing ID, always coverage-incomplete.

Run #43 exposed CSS/no-js card pollution and a postal-only parsing bug. Those were repaired and regression-tested. A one-time fail-closed purge of the malformed #43 data then reported:

- source_listings=35;
- affected_jobs=35;
- exclusive_jobs=35;
- shared_jobs=0;
- purge_safe=yes.

Clean rebuild #45:

- 5/5 shards, 0 failed;
- exactly 5 HTTP requests, zero details;
- 37 seen / 37 new;
- source_reported=5,360;
- 37 relevant-active canonical jobs;
- 37 locations, 27 geo-resolved;
- 2 source PLZ resolved, 25 city approximations, 10 unresolved;
- no CSS title/company-as-location pollution remained.

StepStone acquisition/parser work is closed for now absent a new generic live regression.

### willhaben Jobs — production #46

Design: five first-page search requests, zero details, stable `/jobs/job/<slug>/<id>` identity.

Run #44 had a bad global count regex but clean vacancy parsing. After fixing the count parser, refresh #46 produced:

- 5/5 shards, 0 failed;
- exactly 5 HTTP requests, zero details;
- 18 seen / 0 new / 18 updated;
- sane source_reported=448 rather than ~1.07M;
- 18 relevant-active canonical jobs;
- 17 locations, 15 geo-resolved, 2 unresolved.

Willhaben acquisition/parser work is closed for now absent regression.

## Supplementary broad APIs

Adzuna Austria and Jooble Austria remain implemented/tested but have not been production-run because credentials were not supplied. They are optional corpus bonuses, not the current priority.

## Acquisition phase status

Acquisition micro-polishing is now paused intentionally. Source health is clean for all active job frontiers/feeds, and the first duplicate audit reported:

- relevant_canonical_jobs=163;
- already_multi_listing_canonical_jobs=0;
- no database changes from the audit.

Do not interpret 163 as 163 unique vacancies until canonical duplicate collapse is complete.

## Canonical job dedupe — current primary work

Files:

- `app/jobs/dedupe.py`
- `scripts/job_duplicate_audit.py`
- `tests/test_job_dedupe.py`
- `app/jobs/merge.py`
- `scripts/merge_duplicate_jobs.py`
- `tests/test_job_merge.py`

### First production duplicate audit

The first read-only audit on the 163-job corpus returned 14 high-confidence pair edges and 0 medium under the initial rule set.

Very strong obvious examples included:

- PEISCHL Fahrzeugbau karriere.at ↔ StepStone, exact title/company/Stegersbach;
- Global Hydro karriere.at ↔ StepStone, exact title/company/Niederranna;
- IVM karriere.at ↔ StepStone, exact title/company/Linz;
- APS Group jobs.at ↔ willhaben, normalized exact title/company/Frohnleiten;
- Oberaigner StepStone German/English card variants in Nebelberg;
- Austro Holding SmartRecruiters ↔ StepStone;
- TSMG two Lever punctuation/title variants.

The audit also exposed a critical ambiguity cluster: canonical jobs 164/165/169/208 were all `Konstrukteur (m/w/d)` at Trenkwalder. Some had no location, while jobs 165 and 208 were Klagenfurt variants. The initial rule `same company + normalized exact title + no explicit location conflict` was therefore too permissive for generic titles. No merge was performed.

### Refined duplicate evidence

Current dedupe rules are deliberately stricter:

- known different normalized companies are a hard conflict;
- gender suffixes such as `(m/w/d)`, `all genders`, and bare `m|f|d` are normalized away;
- `Klagenfurt`, `Klagenfurt am Wörthersee`, and ASCII `Klagenfurt am Worthersee` canonicalize together;
- generic titles such as `Konstrukteur`, `Mechanical Engineer`, `Entwicklungsingenieur`, etc. do **not** become high confidence from company alone;
- generic title + company requires location overlap or strong description-overlap evidence for high confidence;
- specific long normalized-exact titles at the same company may still be high without a location when no conflict exists;
- descriptions use conservative token-containment similarity so a board snippet can match a fuller detail description;
- audit output now includes `description_similarity`, generic-title flag, source listing IDs and URLs.

This refinement is designed specifically to split safe duplicate evidence from staffing-agency/template-title coincidences.

### Fail-closed canonical merge engine

`merge_duplicate_jobs.py` is dry-run by default and accepts explicit canonical Job IDs only. It never automatically merges every audit hit.

Safety behavior:

- group must be connected by **high-confidence** duplicate evidence;
- conflicting normalized companies block the merge;
- conflicting canonical salary bundles block the merge rather than silently choosing one;
- survivor is chosen automatically by canonical richness: structured salary, PLZ/geography, description depth, listing count, then stable lower-ID tie-break;
- richer description/company and non-conflicting salary bundle are preserved;
- all `JobListing` rows are moved to the survivor, preserving independent source lifecycle/raw payloads;
- locations are unioned and obvious equivalent city/PLZ rows deduplicated/enriched;
- canonical hash is cleared because merged identity must not retain a stale pre-merge hash;
- conflicting/non-uniform fit score is cleared for future recomputation;
- absorbed canonical Jobs are deleted only after listings/locations have been transferred;
- `--apply` is required for mutation.

CI #369 passed Ruff, Compile and the full test suite for the refined dedupe + merge-plan state.

## Immediate work order

1. Pull current `bootstrap/austria-mvp`.
2. Run only the refined read-only audit:
   `python scripts/job_duplicate_audit.py --include-medium --limit 100`.
3. Inspect the new high/medium groups including listing IDs/URLs and description similarity.
4. Do **not** bulk merge all candidates.
5. For each clearly safe connected group, run `scripts/merge_duplicate_jobs.py <ids...>` in dry-run mode first.
6. Apply only groups whose dry-run reports `safe=yes` and no salary/company/evidence blockers.
7. Re-run duplicate audit after approved merges; canonical count should fall while `already_multi_listing_canonical_jobs` rises.
8. Once obvious duplicates are collapsed, shift primary work to normalized role/domain/task/method/tool concepts, candidate can/want fit, German profile review and house/job recommendation ranking.
