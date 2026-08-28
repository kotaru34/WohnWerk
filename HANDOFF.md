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

## karriere.at — production #40 stable

Files: `app/sources/job/karriere_at.py`, `scripts/run_karriere_at_jobs.py`, tests.

Production #40:

- 5/5 shards, 35 HTTP requests;
- 30 seen / 30 new / all 30 relevant;
- source-reported counts summed to 435;
- 34 relevant locations, 27 geo-resolved;
- 27 structured salaries, 15 annualized;
- no source/rate-limit errors.

Do not deepen traversal yet.

## jobs.at — production #41 stable

Current broad searches: Maschinenbau, Konstrukteur, CAD Konstrukteur, Mechanischer Konstrukteur, SolidWorks.

Production #41:

- 5/5 shards, 18 HTTP requests;
- 13 seen / 13 new / all 13 relevant;
- 14 relevant locations, 7 geo-resolved;
- 12 structured salaries + 1 salary text.

`E-Plan` roles may remain in broad acquisition and later rank down via candidate fit. Do not micro-tune discovery merely for those roles.

## StepStone Austria — production #43 + final live parser cleanup

Files: `app/sources/job/stepstone_at.py`, `scripts/run_stepstone_at_jobs.py`, tests.

Design is exceptionally light: five search pages, zero detail pages, stable numeric listing ID, always coverage-incomplete.

Production #43 after the initial whole-card-anchor repair:

- 5/5 shards, 5 HTTP requests;
- 35 relevant sightings, 32 new + 3 updated;
- source-reported search counts summed to 5,360;
- 35 locations, 22 geo-resolved;
- 8 rejected candidates in audit.

Run #43 exposed remaining live markup issues rather than source failures:

- StepStone emits logo links and title links to the same vacancy, with Emotion/no-js CSS inside the anchors.
- A logo CSS fragment could become a bogus title; because the same stable ID then deduped the real title link, company/location shifted into the wrong fields.
- Symptoms included CSS in rejection audit and bogus unresolved locations `Flach & Barfigo Personalleasing GmbH` and `VirtuRail GmbH`.
- `4973, Österreich` is a real source location and must be interpreted as source PLZ `4973`, not city `4973`.
- StepStone AT can also surface explicitly foreign results such as `München`.

Final parser behavior now committed:

- pure CSS/no-js anchors are ignored;
- CSS prefixes sharing one text node with a visible title are stripped up to the final `}` and the human suffix is retained;
- duplicate logo/title links therefore resolve to the actual title card;
- postal-only `4973, Österreich` preserves `postal_code=4973`, city unknown;
- explicit foreign-country labels and a conservative set of obvious foreign cities such as München are rejected from the Austria corpus;
- ambiguous labels such as St. Gallen/Nußbach/Niederranna are not guessed away;
- regression tests cover CSS logo/title variants, whole-card anchors, postal-only locations and obvious foreign locations.

CI #352 passed Ruff, Compile and the full test suite for this final parser state.

Because #43 already persisted a few malformed StepStone `JobLocation` rows, do one fail-closed technical reset before the next run: `scripts/purge_job_source_listings.py stepstone.at --apply`. The utility refuses modification if any affected canonical Job is shared with another source. If safe, rerun StepStone immediately to rebuild clean rows. This reset is parser maintenance, not a strategy change.

## willhaben Jobs — production #44 stable, count parser fixed

Files: `app/sources/job/willhaben_jobs.py`, `scripts/run_willhaben_jobs.py`, tests.

Design: five first-page search requests, zero details, stable `/jobs/job/<slug>/<id>` identity, card-level company/date/location/snippet.

Production #44:

- 5/5 shards, exactly 5 HTTP requests;
- 18 seen / 18 new / 18 relevant;
- 17 relevant locations, 15 geo-resolved;
- only Nußbach and Salzburg Stadt unresolved;
- 5 rejected candidates in audit.

The jobs themselves parsed cleanly. Only `source_reported` was wrong (`1,068,927`) because the count regex was too broad and could latch onto unrelated page-global numeric/Jobs text.

Current fix accepts only search-specific forms `N Anzeigen` or `N Jobs für ...`. Regression includes willhaben navbar noise (`Jobs 15.342`) plus a real query count and verifies the query count wins. No purge is needed; rerun willhaben once to refresh run metadata with sane counts.

## Adzuna + Jooble supplementary APIs

Both are implemented and tested. Keep them as optional extra corpus sources:

- Adzuna Austria: five API queries/run, credentials via `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` only.
- Jooble Austria: five API queries/run, key via `JOOBLE_AT_API_KEY` only.

No production run yet because credentials were not supplied. They are not the current priority.

## Current broad-board corpus direction

Before cross-board canonical dedupe, current live relevant listings are roughly:

- karriere.at: 30
- jobs.at: 13
- StepStone #43: 35 (needs one clean rebuild because a few persisted fields are malformed)
- willhaben: 18

This is about 96 board listings before cross-board duplicate collapse, plus SmartRecruiters/Personio/Lever. Do not call 96 unique jobs.

## Immediate work order

1. Pull the latest branch and run tests.
2. Fail-closed purge/reset StepStone once; if the purge reports a shared canonical Job it will abort rather than damage it.
3. Re-run StepStone: expected 5/5, 5 requests, 0 details, no CSS title/company-as-location pollution, and `4973` preserved as PLZ.
4. Re-run willhaben once: expected 5/5, 5 requests, 0 details, with sane per-query `source_reported` counts rather than ~213k each.
5. Resolve locations and inspect StepStone/willhaben stats + rejection audit + source health.
6. If those are clean, stop acquisition micro-polishing for now.
7. Next primary work: quantify/collapse obvious cross-board duplicates, introduce normalized role/domain/task/method/tool concepts, then candidate can/want fit and German profile/recommendation UI.
