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

Dry-run then exposed one important false-safe case: teampool jobs 163/168 are same-source, near-identical title/body variants, but explicit locations disagree (`Wien` vs `Wels`). Merge safety was tightened before applying anything.

### First applied merge batch

The following seven explicit groups were applied successfully:

- 131/225 — PEISCHL Fahrzeugbau, karriere.at + StepStone, survivor 131.
- 136/240 — Global Hydro, karriere.at + StepStone, survivor 136.
- 155/255 — IVM Technical Consultants, karriere.at + StepStone, survivor 155.
- 157/227 — Trenkwalder E-Plan, jobs.at + StepStone, survivor 157.
- 159/206 — APS Group, jobs.at + willhaben, survivor 159.
- 165/208 — Trenkwalder Klagenfurt, jobs.at + willhaben, survivor 165.
- 251/252 — Oberaigner StepStone German/English card variants, survivor 251.

Observed post-merge state matched the prediction exactly:

- `relevant_canonical_jobs=156`
- `already_multi_listing_canonical_jobs=7`

No bulk merge was used; every group was explicit and fail-closed.

### Post-merge audit before audit/ORM cleanup

The immediate post-merge read-only audit showed:

- `duplicate_candidates_high=1`
- `duplicate_candidates_medium=6`

The one remaining high edge was teampool 163/168. It was not merged because the merge engine correctly reported:

`same-source explicit locations conflict; jobs=163,168 sources=jobs.at left=city:wien right=city:wels`

Remaining medium cases include:

- TSMG 3/4 — same Lever source, same normalized title/location, weak description overlap 0.307;
- Austro Holding 34/228 — SmartRecruiters ↔ StepStone Mechanical Engineer, generic title, weak evidence;
- Trenkwalder generic `Konstrukteur` edges involving 164/165/169;
- Anton Paar 67/68 — same SmartRecruiters source, DE/EN-ish service-engineer titles but distinct IDs and weak body overlap.

Leave all of these untouched absent stronger evidence.

## Current duplicate evidence policy

Rules are deliberately conservative:

- known different normalized companies are a hard conflict;
- gender suffixes normalize away;
- Klagenfurt naming variants canonicalize together;
- generic titles are conservative;
- descriptions use token-containment similarity so snippets can match full descriptions;
- audit prints source listing IDs/URLs, description similarity, generic-title and shared-source flags;
- cross-board exact company/title/location is strong syndication evidence;
- same-source different listing IDs are possible parallel openings;
- same-source non-generic needs `description_similarity >= 0.82` for high evidence;
- same-source generic/template needs `description_similarity >= 0.95`;
- otherwise pairs remain medium.

## Fail-closed canonical merge engine

`merge_duplicate_jobs.py` is dry-run by default and accepts explicit canonical Job IDs only.

Safety behavior:

- group must be connected by high-confidence evidence;
- conflicting normalized companies block merge;
- conflicting canonical salary bundles block merge;
- same-source explicit location disagreement blocks merge even if title/body evidence is strong;
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

### ORM warning cleanup after first merge batch

The first applied batch exposed SQLAlchemy warnings when equivalent `JobLocation` rows were deduplicated:

`DELETE statement on table 'job_locations' expected to delete 1 row(s); 0 were matched`

Root cause: the merge code explicitly called `session.delete(location)` and then deleted the absorbed parent Job whose `locations` relationship already uses `cascade="all, delete-orphan"`; ORM therefore attempted a second delete for the same child row.

Current fix removes duplicate locations from the absorbed relationship and lets delete-orphan own the deletion. This avoids the double-delete path without changing merge semantics.

### Audit/merge-safety alignment

The audit previously reported raw duplicate evidence only, so teampool 163/168 could still appear as `high` even though destructive merge safety blocked it.

Current audit now runs the same fail-closed merge plan for every raw high-evidence pair and splits output into:

- `duplicate_candidates_high` — high evidence and merge-plan safe;
- `duplicate_candidates_blocked` — high evidence but unsafe to merge, with explicit blockers;
- `duplicate_candidates_medium` — unresolved evidence only.

On the current production corpus the expected next read-only audit is:

- `relevant_canonical_jobs=156`
- `already_multi_listing_canonical_jobs=7`
- `duplicate_candidates_high=0`
- `duplicate_candidates_blocked=1` (teampool 163/168 Wien/Wels)
- `duplicate_candidates_medium=6`

CI #382 passed Ruff, Compile and the full test suite for the ORM-delete cleanup and audit/merge-safety alignment.

## Immediate work order

1. Pull current `bootstrap/austria-mvp`.
2. Run only `python scripts/job_duplicate_audit.py --include-medium --limit 100`.
3. Confirm expected `156 / 7 / high=0 / blocked=1 / medium=6` state.
4. Do not merge blocked or medium pairs.
5. Once confirmed, consider canonical dedupe sufficiently closed for this corpus.
6. Shift primary work to normalized role/domain/task/method/tool concepts, candidate can/want fit, German profile review and house/job recommendation ranking.
