# WohnWerk handoff checkpoint

**Checkpoint date:** 2026-08-27 (Europe/Berlin)  
**Project:** WohnWerk  
**Repository:** `kotaru34/WohnWerk`  
**Active branch:** `bootstrap/austria-mvp`  
**Draft PR:** #1 — `Bootstrap Austria-first WohnWerk MVP`  

This file is the recovery point for continuing WohnWerk in a fresh ChatGPT/Codex context.

## Current production/job acquisition state

- Property acquisition remains stable: IMMMO run #11 and s REAL run #16.
- Lever calibration remains stable at run #22.
- Personio calibration remains stable at run #24 and is the next ATS to scale after SmartRecruiters correctness/liveness validation.
- SmartRecruiters run #32 completed successfully with coverage OK, 15/15 shards, 41 current relevant rows, 43 relevant-active persisted rows, 42/43 relevant locations resolved, and `disappeared=0`.
- Gate v11 restored the intended German parity cases (`Servicetechniker`, technical `Teamleitung`) and correctly classifies `Student Employee` as structural student-stage.
- `Großraum Linz, Steyr,Wels` multi-locality resolution is implemented and no longer unresolved.

## Important freshness/liveness concern discovered after run #32

Do not assume an ATS/API row is sufficient proof that a candidate can still apply.

SmartRecruiters currently remains a strong discovery source, and its Posting API documents `/postings` as active postings. The specific Anton Paar `Konstrukteur für Kunststoffteile (w/m/d)` vacancy is also currently listed on Anton Paar's own `Offene Stellen` pages and appears recently in external indexes, suggesting a republish/reuse of an older page rather than a confirmed stale listing. However, WohnWerk must independently audit application liveness instead of trusting only source lifecycle.

The adapter already stores:

- `smartrecruiters_released_date`
- `smartrecruiters_apply_url`
- source/public posting URL

A new read-only liveness audit is being added to inspect:

1. `releasedDate` age;
2. public posting URL HTTP state;
3. apply URL HTTP state;
4. explicit closed/expired/no-longer-accepting text;
5. missing/unknown evidence separately from confirmed closure.

Age alone must **not** deactivate a posting; legitimate long-running or republished roles exist. HTTP anti-bot/transient failures must remain `unknown`, not `dead`.

If the audit shows meaningful false-active rates, add an independent application-liveness state/confidence layer before scaling ATS coverage. Do not overload `JobListing.status`; source lifecycle and application liveness are separate dimensions.

## Next immediate work

1. Finish/validate the read-only SmartRecruiters liveness audit and run CI.
2. Production: run targeted audit for Anton Paar `Konstrukteur für Kunststoffteile`, then full current relevant SmartRecruiters corpus.
3. Quantify confirmed live / dead / unknown and release-age distribution.
4. Only if evidence warrants it, integrate liveness verification into ingestion/reconciliation semantics.
5. Then fix the generic `intern` regex false positive (`internal` / `international` currently can hit student-stage) and stop SmartRecruiters gate micro-calibration.
6. Move to Personio bulk tenant discovery/import.

## Core invariants

- All user-facing WohnWerk UI must be German.
- Do not ask for or print DB passwords.
- `JobListing.status` is source lifecycle only.
- Professional relevance is independent (`wohnwerk_discovery_gate.accepted`).
- Application liveness/freshness must also be independent.
- Taxonomy changes must never masquerade as source disappearance.
- New rejected candidates are normally not durably persisted.
- Failed/partial reconciliation never mass-deactivates.
- No fake PLZ for approximate locations.
- House/job geography uses PostGIS and remains separate from intrinsic job fit.
- No CAPTCHA bypass, credential theft, fingerprint spoofing, or deliberate anti-bot evasion.
