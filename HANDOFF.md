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

Consumer-board acquisition should behave like a person quickly scanning vacancies:

- a handful of broad/focused searches;
- first result page initially;
- stable-ID dedupe;
- details only when useful and title looks interesting;
- sequential low-rate requests;
- no whole-site crawl, aggressive pagination or reconciliation for these frontiers;
- ToS text can inform priority but is advisory rather than an architecture blocker by itself;
- no technical anti-bot bypass.

Do not return to the earlier permission-first/purge detour. Adzuna/Jooble are supplementary APIs, not replacements for normal boards.

## Stable property acquisition

Do not reopen absent live regression:

- IMMMO #11: coverage OK, 13,948 seen, 1,167 pages, 9/9 shards, disappeared=0.
- s REAL #16: coverage OK, 314 seen, detail-enriched, disappeared=0.
- ImmoAds retired/disabled.

## Stable supplementary ATS job sources

- SmartRecruiters #33: 42 relevant-active canonical jobs; 41/42 relevant locations resolved.
- Personio #37: 17 relevant-active jobs; only `österreichweit` intentionally unresolved.
- Lever #22: 6 relevant jobs, all relevant locations resolved.

ATS feeds remain supplementary. Do not scale primarily by manually enumerating employers.

## Discovery gate / candidate direction

Current gate: `profile-seed-2026-08-28-v14`. Generic discovery correctness is closed unless a genuinely generic bug appears.

Candidate is fundamentally mechanical/Maschinenbau, not electrical. Future fit should strongly prefer mechanical CAD/construction, components/assemblies, automotive/special-vehicle/rail work, product development, technical project work, supplier coordination and mechanically relevant validation/testing. Pure electrical engineering is future fit `cannot + not want`; this affects candidate fit, not broad acquisition.

## Stable low-impact broad boards

### karriere.at — production #40

- 5/5 shards, 35 HTTP requests;
- 30 relevant jobs;
- 34 relevant locations, 27 geo-resolved;
- 27 structured salaries, 15 annualized.

### jobs.at — production #41

Broad searches: Maschinenbau, Konstrukteur, CAD Konstrukteur, Mechanischer Konstrukteur, SolidWorks.

- 5/5 shards, 18 HTTP requests;
- 13 relevant jobs;
- 14 relevant locations, 7 geo-resolved;
- 12 structured salaries + 1 salary text.

### StepStone Austria — clean production #45

- 5/5 shards, 0 failed;
- exactly 5 HTTP requests, zero details;
- 37 relevant jobs;
- 37 locations, 27 geo-resolved;
- 2 source PLZ resolved;
- no CSS/title/location pollution remains.

### willhaben Jobs — production #46

- 5/5 shards, 0 failed;
- exactly 5 HTTP requests, zero details;
- 18 relevant jobs;
- sane source_reported=448;
- 17 locations, 15 geo-resolved.

Acquisition micro-polishing is paused intentionally.

## Canonical job dedupe — current primary work

Files:

- `app/jobs/dedupe.py`
- `scripts/job_duplicate_audit.py`
- `tests/test_job_dedupe.py`
- `app/jobs/merge.py`
- `scripts/merge_duplicate_jobs.py`
- `tests/test_job_merge.py`

Current pre-merge corpus:

- `relevant_canonical_jobs=163`
- `already_multi_listing_canonical_jobs=0`

No audit has changed the database.

### Final production audit before first merge batch

After iterative tightening, the final read-only audit produced exactly:

- `duplicate_candidates_high=8`
- `duplicate_candidates_medium=8`

High pairs:

- 131/225 — PEISCHL Fahrzeugbau, karriere.at ↔ StepStone, Stegersbach, description overlap 0.971.
- 136/240 — Global Hydro, karriere.at ↔ StepStone, Niederranna.
- 155/255 — IVM Technical Consultants, karriere.at ↔ StepStone, Linz.
- 157/227 — Trenkwalder E-Plan Konstrukteur, jobs.at ↔ StepStone, description overlap 1.000.
- 159/206 — APS Group, jobs.at ↔ willhaben, Frohnleiten.
- 163/168 — teampool, same jobs.at source, description overlap 0.950.
- 165/208 — Trenkwalder Konstrukteur, jobs.at ↔ willhaben, Klagenfurt naming variants.
- 251/252 — Oberaigner, same StepStone source, German/English variants, description overlap 1.000.

Medium includes TSMG 3/4, Austro Holding 34/228, the ambiguous Trenkwalder 164/165/169/208 edges, and Anton Paar 67/68.

### Dry-run findings

All eight high pairs initially reported `safe=yes`, but dry-run exposed one safety gap:

- 163 has source location text `Wien, Österreich`, remote=true;
- 168 has `Wels, Oberösterreich, Österreich`, remote=true;
- both are separate jobs.at listing IDs with nearly identical staffing-template text.

This can represent parallel location-targeted openings and must not be merged merely because body text is similar.

Therefore **do not apply 163/168**.

The remaining seven pairs are the first approved apply candidates:

- 131/225
- 136/240
- 155/255
- 157/227
- 159/206
- 165/208
- 251/252

Expected post-merge corpus if all seven apply cleanly:

- `relevant_canonical_jobs=156`
- `already_multi_listing_canonical_jobs=7`

### Current duplicate evidence policy

Rules are deliberately conservative:

- known different normalized companies are a hard conflict;
- gender suffixes normalize away;
- Klagenfurt naming variants canonicalize together;
- generic titles are conservative;
- descriptions use token-containment similarity so snippets can match full descriptions;
- audit prints source listing IDs/URLs, description similarity, generic-title and shared-source flags;
- cross-board exact company/title/location is strong syndication evidence;
- same-source different listing IDs are possible parallel openings;
- same-source non-generic needs `description_similarity >= 0.82` for high confidence;
- same-source generic/template needs `description_similarity >= 0.95` for high confidence;
- otherwise pairs remain medium.

## Fail-closed canonical merge engine

`merge_duplicate_jobs.py` is dry-run by default and accepts explicit canonical Job IDs only.

Safety behavior:

- group must be connected by high-confidence evidence;
- conflicting normalized companies block merge;
- conflicting canonical salary bundles block merge;
- **same-source explicit location disagreement now blocks merge even if title/body evidence is strong**;
- sparse location text such as `Wien, Österreich` is conservatively reduced to its explicit first locality only for this merge-safety check;
- countrywide/remote-only labels do not invent a locality;
- survivor is chosen by canonical richness;
- richer description/company and non-conflicting salary bundle are preserved;
- all JobListing rows move to the survivor with source lifecycle/raw payloads preserved;
- locations are unioned and equivalent rows deduplicated/enriched;
- stale canonical hash is cleared;
- conflicting/non-uniform fit score is cleared for recomputation;
- absorbed Jobs are deleted only after transfers;
- `--apply` is required.

Regression tests cover the teampool-style same-source `Wien` vs `Wels` conflict and an equivalent-location same-source case.

CI #379 passed Ruff, Compile and the full test suite for the location-conflict guard.

## Immediate work order

1. Pull current `bootstrap/austria-mvp`.
2. Optionally dry-run `163 168` once to verify the new blocker reports `safe=no` with Wien/Wels conflict.
3. Apply only the seven approved groups: 131/225, 136/240, 155/255, 157/227, 159/206, 165/208, 251/252.
4. Re-run duplicate audit immediately.
5. Expected canonical count is 156 and multi-listing canonical count is 7 if all seven merge successfully.
6. Leave TSMG/Austro Holding/Anton Paar/ambiguous staffing-template medium pairs and teampool 163/168 untouched.
7. If post-merge audit is clean, shift primary work to normalized role/domain/task/method/tool concepts, candidate can/want fit, German profile review and house/job recommendation ranking.
