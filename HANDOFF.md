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

- karriere.at #40: 30 relevant jobs, 35 requests, 27 structured salaries.
- jobs.at #41: 13 relevant jobs, 18 requests, 12 structured salaries + 1 salary text.
- StepStone #45: 37 relevant jobs, exactly 5 requests, zero details, 27 geo-resolved.
- willhaben #46: 18 relevant jobs, exactly 5 requests, zero details, source_reported=448.

Acquisition micro-polishing is paused intentionally.

## Canonical job dedupe — first production merge completed

Files:

- `app/jobs/dedupe.py`
- `scripts/job_duplicate_audit.py`
- `tests/test_job_dedupe.py`
- `app/jobs/merge.py`
- `scripts/merge_duplicate_jobs.py`
- `tests/test_job_merge.py`

### Pre-merge state

Final refined read-only audit before mutation:

- `relevant_canonical_jobs=163`
- `already_multi_listing_canonical_jobs=0`
- `duplicate_candidates_high=8`
- `duplicate_candidates_medium=8`

Dry-run exposed one false-safe case: teampool jobs 163/168 are same-source near-identical title/body variants but explicit locations disagree (`Wien` vs `Wels`). Merge safety was tightened before mutation.

### First applied merge batch

Seven explicit groups were applied successfully:

- 131/225 — PEISCHL Fahrzeugbau, karriere.at + StepStone, survivor 131.
- 136/240 — Global Hydro, karriere.at + StepStone, survivor 136.
- 155/255 — IVM Technical Consultants, karriere.at + StepStone, survivor 155.
- 157/227 — Trenkwalder E-Plan, jobs.at + StepStone, survivor 157.
- 159/206 — APS Group, jobs.at + willhaben, survivor 159.
- 165/208 — Trenkwalder Klagenfurt, jobs.at + willhaben, survivor 165.
- 251/252 — Oberaigner StepStone German/English variants, survivor 251.

Observed post-merge state matched the prediction exactly:

- `relevant_canonical_jobs=156`
- `already_multi_listing_canonical_jobs=7`

No bulk merge was used; every group was explicit and fail-closed.

### Post-merge unresolved candidates

Immediate post-merge audit had one raw high edge and six medium edges.

The raw high edge is teampool 163/168, but merge safety correctly blocks it:

`same-source explicit locations conflict; jobs=163,168 sources=jobs.at left=city:wien right=city:wels`

Remaining medium cases include TSMG 3/4, Austro Holding 34/228, Trenkwalder generic `Konstrukteur` edges around 164/165/169, and Anton Paar 67/68. Leave all untouched absent stronger evidence.

## Current duplicate evidence and merge policy

- known different normalized companies are a hard conflict;
- gender suffixes normalize away;
- Klagenfurt naming variants canonicalize together;
- generic titles are conservative;
- descriptions use token-containment similarity;
- cross-board exact company/title/location is strong syndication evidence;
- same-source different listing IDs are possible parallel openings;
- same-source non-generic needs description similarity >=0.82 for high evidence;
- same-source generic/template needs >=0.95;
- conflicting normalized companies or salary bundles block merge;
- same-source explicit location disagreement blocks merge;
- survivor is chosen by canonical richness;
- JobListings/raw payloads and non-conflicting richer canonical data are preserved;
- locations are unioned/deduplicated;
- stale canonical hash and ambiguous fit score are cleared;
- `--apply` is always required.

### ORM warning cleanup

The first applied batch exposed `SAWarning` on deduplicated `JobLocation` rows. Root cause was a double-delete path: explicit `session.delete(location)` followed by deletion of the absorbed parent whose relationship already has `cascade="all, delete-orphan"`.

Current code removes the duplicate child from the absorbed relationship and lets delete-orphan own the deletion. Merge semantics are unchanged; the warning path is removed.

### Audit/merge-safety alignment

Audit now runs the same fail-closed merge plan for every raw high-evidence pair and reports three classes:

- `duplicate_candidates_high` — high evidence and merge-plan safe;
- `duplicate_candidates_blocked` — high evidence but unsafe, with blockers;
- `duplicate_candidates_medium` — unresolved evidence.

Expected next production audit on the already-merged corpus:

- `relevant_canonical_jobs=156`
- `already_multi_listing_canonical_jobs=7`
- `duplicate_candidates_high=0`
- `duplicate_candidates_blocked=1` — teampool 163/168 Wien/Wels
- `duplicate_candidates_medium=6`

CI #382 passed Ruff, Compile and the full test suite for the ORM-delete cleanup and audit/merge-safety alignment.

## Immediate work order

1. Pull current `bootstrap/austria-mvp`.
2. Run only `python scripts/job_duplicate_audit.py --include-medium --limit 100`.
3. Confirm expected `156 / 7 / high=0 / blocked=1 / medium=6` state.
4. Do not merge blocked or medium pairs.
5. Then consider canonical dedupe closed for the current corpus and move to normalized role/domain/task/method/tool concepts, candidate can/want fit, German profile review and house/job recommendation ranking.
