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
- details only when actually useful and title looks interesting;
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

Design: five search pages, zero details, stable numeric listing ID, always coverage-incomplete.

After the one-time parser cleanup/reset:

- 5/5 shards, 0 failed;
- exactly 5 HTTP requests, zero details;
- 37 relevant jobs;
- 37 locations, 27 geo-resolved;
- 2 source PLZ resolved;
- no CSS/title/location pollution remains.

### willhaben Jobs — production #46

Design: five first-page search requests, zero details.

- 5/5 shards, 0 failed;
- exactly 5 HTTP requests, zero details;
- 18 relevant jobs;
- sane source_reported=448;
- 17 locations, 15 geo-resolved.

Acquisition micro-polishing is now paused intentionally.

## Supplementary broad APIs

Adzuna Austria and Jooble Austria remain implemented/tested but have not been production-run because credentials were not supplied. They are optional corpus bonuses.

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

### Production audit history

Initial audit under the first rule set:

- 14 high-confidence edges;
- 0 medium;
- exposed an over-permissive Trenkwalder `Konstrukteur` cluster.

Second audit after generic-title/location refinement:

- 10 high-confidence edges;
- 6 medium-confidence edges.

Strong cross-board evidence included PEISCHL, Global Hydro, IVM, E-Plan/Trenkwalder, APS Group and the Klagenfurt Trenkwalder syndication. Same-source strong examples included teampool and Oberaigner.

The second audit exposed two remaining risks:

1. TSMG jobs 3/4 are separate Lever listing IDs with the same normalized title/location but only `description_similarity=0.307`; same-source exact title/location is therefore not sufficient.
2. Trenkwalder jobs 164/169 are same-source generic `Konstrukteur` titles with `description_similarity=0.888`; staffing-agency template reuse can make that look stronger than it really is.

### Current duplicate evidence policy

Current rules are deliberately conservative:

- known different normalized companies are a hard conflict;
- gender suffixes such as `(m/w/d)`, `all genders`, bare `m|f|d` normalize away;
- Klagenfurt naming variants canonicalize together;
- generic titles are treated conservatively;
- descriptions use token-containment similarity so snippets can match fuller descriptions;
- source listing IDs/URLs, description similarity, generic-title flag and shared-source flag are printed by the audit;
- cross-board exact company/title/location is strong syndication evidence;
- **same-source** different listing IDs are treated as possible parallel openings rather than automatic duplicates;
- same-source non-generic pairs need `description_similarity >= 0.82` for high confidence;
- same-source generic/template pairs need `description_similarity >= 0.95` for high confidence;
- otherwise matching same-company titles remain medium rather than being destructively merged.

This should downgrade TSMG 3/4 and the ambiguous generic Trenkwalder 164/169 pair while retaining strong Oberaigner/teampool same-source variants.

CI #376 passed Ruff, Compile and the full test suite for these final thresholds.

## Fail-closed canonical merge engine

`merge_duplicate_jobs.py` is dry-run by default and accepts explicit canonical Job IDs only. It never automatically merges every audit hit.

Safety behavior:

- group must be connected by high-confidence evidence;
- conflicting normalized companies block merge;
- conflicting canonical salary bundles block merge;
- survivor is chosen by canonical richness: structured salary, PLZ/geography, description depth, listing count, then lower-ID tie-break;
- richer description/company and non-conflicting salary bundle are preserved;
- all `JobListing` rows move to the survivor with independent source lifecycle/raw payloads preserved;
- locations are unioned and obvious equivalent city/PLZ rows deduplicated/enriched;
- stale canonical hash is cleared;
- conflicting/non-uniform fit score is cleared for recomputation;
- absorbed canonical Jobs are deleted only after transfers;
- `--apply` is required for mutation.

## Immediate work order

1. Pull current `bootstrap/austria-mvp`.
2. Run the final refined read-only audit:
   `python scripts/job_duplicate_audit.py --include-medium --limit 100`.
3. Expect TSMG and ambiguous same-source staffing/template pairs to be downgraded.
4. Dry-run clearly safe high-confidence groups with `scripts/merge_duplicate_jobs.py <ids...>`; no `--apply` yet.
5. Inspect salary/company/evidence blockers and survivor choice.
6. Apply only explicitly safe groups.
7. Re-run duplicate audit; canonical count should fall and multi-listing canonicals should rise by predictable amounts.
8. Leave TSMG/Austro Holding/Anton Paar and other ambiguous medium cases untouched until stronger evidence exists.
9. Then shift primary work to normalized role/domain/task/method/tool concepts, candidate can/want fit, German profile review and house/job recommendation ranking.
