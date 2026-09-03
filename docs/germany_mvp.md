# Germany MVP contract

**Status:** active development contract for `feature/germany`  
**Baseline:** frozen Austria behavior remains the compatibility baseline  
**Scope:** Germany-oriented MVP implemented alongside Austria

This document is the authoritative Germany product/acquisition contract. Read it immediately after `HANDOFF.md` in a fresh context.

## Goal

WohnWerk is a private/self-hosted application for finding suitable houses and jobs and matching them geographically for the candidate/father.

Germany must be a first-class market without changing frozen Austria behavior. The product is a private discovery/index layer that links back to original sources, not a portal mirror.

Immediate goals:

1. acquire a high-recall index of German houses for sale inside the configured budget;
2. acquire relevant German jobs;
3. keep DE/AT acquisition and lifecycle state isolated by source country;
4. expose Häuser / Jobs / Matching for either market with one country switch;
5. retain only source-backed facts needed for filtering, ranking, lifecycle and linking.

## Country/UI model

- source country comes from `Source.config["country_code"]`;
- legacy sources without country metadata are treated as `AT`;
- supported UI countries are `DE` and `AT`;
- country selection scopes `/houses`, `/jobs`, and `/admin/matches`;
- father-facing UI remains German-only;
- DE logic must never route German records through Austria-specific locality assumptions;
- favorites/hidden/viewed and matching semantics remain compatible across countries.

## Germany property scope

Configured product budget:

```text
EUR 30,000 .. 300,000
```

Current portal adapters use 48 deterministic shards:

```text
16 states / city-states
  x EUR 30,000..149,999
  x EUR 150,000..224,999
  x EUR 225,000..300,000
```

The internal price boundaries are engineering shards only. They are **not** product preferences or ranking weights and may be rebalanced if observed result distributions justify it.

Primary broad property sources under development:

- `immoscout24-de`;
- `immowelt-de`;
- provider-authorized OpenImmo feeds where available.

## Public-frontend acquisition policy

Do **not** treat a portal ToS as an automatic technical veto. For this private/self-hosted project, ToS is considered an operational/civil risk signal and source-specific constraint, while the crawler design remains governed by the concrete technical red lines below.

Publicly reachable frontend pages may be acquired carefully with ordinary browser execution when required by the public frontend. A plain HTTP client returning `401/403` does not by itself determine source availability: an ordinary browser renderer may be used when the same public page is normally available to an unauthenticated user.

Allowed engineering progression inside WohnWerk-owned code:

```text
normal public HTTP
    -> ordinary Chromium rendering when the public site requires browser execution
    -> explicit challenge detection
    -> persist exact crawl/browser handoff state
    -> user-provided external challenge-handler boundary
    -> same-run resume after an explicit resolved disposition
```

Red lines for WohnWerk-owned code:

- no login/account automation for commercial portal crawling;
- no CAPTCHA-solving implementation;
- no paywall/access-control bypass implementation;
- no deliberate IP-ban bypass;
- no stealth/anti-bot fingerprint frameworks intended to evade detection;
- no residential/proxy rotation intended to defeat blocking;
- no reverse-engineered private API solely to bypass the normal interface;
- no credential theft or reuse of private login material;
- no aggressive request rates.

Challenge handling is an explicit interface boundary. WohnWerk may detect a challenge, persist crawl and browser state, invoke an operator/user-provided external executable, and consume only its `resolved|defer|abort` disposition. The external handler's internal implementation is outside WohnWerk-owned code and must not be edited by WohnWerk automation. If no handler is configured, or the handler defers/fails, the crawl remains paused/fail-closed without losing its saved position.

Normal browser execution is **not** considered stealth by itself. Use stock Playwright/Chromium behavior without fingerprint-masking plugins in WohnWerk-owned code.

Use conservative delays, caching where useful, standard backoff for transient `429/5xx` responses, and source-level isolation so one portal cannot interrupt unrelated production acquisition.

## Minimal-retention rule for commercial portals

For ImmoScout24/Immowelt discovery retain only what WohnWerk needs:

- source name;
- source listing ID;
- source URL;
- title;
- asking price;
- explicit living area when exposed;
- explicit plot area when exposed;
- PLZ;
- city/locality;
- first/last-seen and internal provenance/lifecycle metadata.

Do not retain from normal commercial-portal discovery:

- full descriptions/body text;
- broker/seller contact details;
- portal-hosted photos or local photo mirrors;
- arbitrary page snapshots as catalog data;
- invented/inferred attributes without source evidence.

A temporary challenge diagnostic screenshot and Playwright storage-state file may be written under the private challenge-state directory for handoff/resume. They are operational state, not catalog data, and must not be exposed in the product UI.

This is a private matching index, not republication of the source database.

## ImmoScout24 Germany

The adapter partitions Germany into the 48 shards above and parses public house-sale search results, but the target-host acquisition path is currently paused/fail-closed.

Target-host observations on 2026-09-02:

- plain `httpx` request to a Sachsen house search returned HTTP `401`;
- stock Playwright Chromium in headless mode returned HTTP `401` with the explicit page `Ich bin kein Roboter - ImmobilienScout24`;
- stock Playwright Chromium in headed mode under Xvfb returned the same HTTP `401` challenge;
- a normal control browser sharing the same public IP also received the challenge initially, then similar public search URLs worked after one manual human CAPTCHA completion;
- this strongly indicates browser/session clearance rather than an IP-only decision.

ImmoScout24 is therefore not in the automatic source scheduler while its production transport remains unvalidated. Stored source data stays available; the global scheduler does not call the paused source.

Search/list-result acquisition remains preferred over unnecessary detail-page crawling.

## Immowelt Germany

Immowelt uses the public `/classified-search` frontend with exact state parameters observed from the normal site UI:

- `distributionTypes=Buy,Buy_Auction,Compulsory_Auction`;
- `estateTypes=House`;
- state/city-state `locations` IDs;
- explicit `priceMin` / `priceMax`;
- `order=DateDesc`;
- `page=N`.

Target-host observations on 2026-09-02:

- stock Playwright Chromium in headless mode returned HTTP `403` for the confirmed public `/classified-search` URL;
- the identical URL in stock Playwright Chromium with `headless=False` under Xvfb returned HTTP `200`;
- the headed response contained 40 normal SERP cards and the expected filtered heading/results;
- `navigator.webdriver` remained `true`, so no automation/fingerprint masking was required;
- the successful path used no login, copied private login state, proxy, or stealth framework.

Accordingly the production Immowelt adapter keeps the confirmed direct `/classified-search` URLs and parser, but launches ordinary headed Chromium on the dedicated WohnWerk Xvfb display. Do not reintroduce the temporary UI-click/warm-session transport experiment unless new evidence invalidates direct headed navigation.

Do not open listing detail pages during normal discovery. Heavy image/media/font resources may be suppressed to avoid needless transfer. Page 250 remains a hard safety cap.

### Immowelt challenge/resume state machine

A `403` or recognized challenge page/frame is not represented as forty-eight shard failures. The crawler must:

1. identify the current `CrawlRun`, shard, Bundesland, price band and exact page/navigation point;
2. persist cumulative page/card/unique-ID counters and the same-run resume cursor;
3. persist the run's already chosen fair shard order;
4. export browser storage state and a diagnostic screenshot when available;
5. mark only the current shard/run as paused, leaving untouched shards unattempted;
6. invoke the user-provided external challenge handler after persistence is committed;
7. on `resolved`, reload the returned/updated browser state and retry the saved navigation point inside the same run;
8. on `defer`, keep the run unfinished and resumable;
9. on `abort` or a source-wide hard failure, count the actual failed shard separately and mark untouched remainder as skipped/not-attempted.

The production runner accepts an external handler via `--challenge-handler` or `WOHNWERK_IMMOWELT_CHALLENGE_HANDLER`. The executable receives one JSON object on stdin and returns one JSON object on stdout:

```json
{"action":"resolved","retry_after_seconds":0}
```

Valid actions are `resolved`, `defer`, and `abort`. WohnWerk invokes the command directly without a shell. The handler may update the supplied persisted `storage_state_path` before returning `resolved`; WohnWerk then recreates its ordinary Chromium context from that state and resumes the saved page. The default when no handler exists is `defer`.

The normal Immowelt command keeps roughly 15-second jittered navigation spacing. HTTP `429` halts the source attempt and relies on the normal source poll interval before another network attempt. Immowelt remains incremental-only in the automatic scheduler while coverage behavior is being validated.

## Coverage and disappearance authority

Discovery success and disappearance authority are separate.

Incremental scans:

- discover new/updated listings;
- may scan only a bounded newest-first frontier;
- never prove disappearance.

A reconciliation may prove disappearance only when:

1. every enabled shard ran;
2. every shard completed successfully;
3. every shard was fully traversed / `coverage_complete=true`;
4. no shard hit a cap;
5. parser identity coverage is complete enough;
6. observed **unique IDs** are plausible against source-reported counts/tolerances where available;
7. a challenge-resumed shard retained complete identity history from the pre-challenge part of the same run.

Partial, capped, challenged, paused, skipped, parser-incomplete or degraded runs are non-authoritative. Never manually promote `Source.coverage_status`. `reconcile_missing_listings()` remains gated on a complete `coverage=ok` reconciliation, so an incomplete/degraded scan cannot deactivate listings because they were absent from that scan.

## Germany postal geography

Germany uses migration `0012_de_postal_codes` and five-digit PLZ.

GeoNames supplies approximate DE postal centroids. Target production bootstrap on 2026-09-02 imported 10,813 DE centroids; the existing 2,234-row Austria postal reference hash remained unchanged. These counts are observations, not permanent invariants.

Austria name/PLZ resolution is explicitly source-scoped so GeoNames DE rows cannot contaminate AT locality resolution.

## Germany jobs

Initial Germany paths include:

- `arbeitsagentur-jobsuche-de` via the public Bundesagentur Jobsuche frontend interface;
- `adzuna-api-de` when credentials are configured;
- existing employer/ATS mechanisms where appropriate.

The Bundesagentur interface is not treated as reconciliation-authoritative merely because discovery works. Intrinsic candidate fit remains geography-independent; country and commute are separate dimensions.

## Data truth rules

- never invent coordinates;
- never invent prices or salary semantics;
- never invent property attributes;
- only explicit living-area evidence maps to living area;
- only explicit plot/land-area evidence maps to plot area;
- ambiguous area values stay ambiguous;
- preserve source provenance;
- dedupe conservatively;
- acquisition failure must not destroy user curation state.

## Current rollout checkpoint

Production now runs on the migrated Debian 13 VM with the established `/opt/wohnwerk` and `/var/lib/wohnwerk` layout, remote HA PostgreSQL through multi-host libpq/psycopg with `target_session_attrs=read-write`, PostGIS 3.5.6, OSRM, Xvfb and the existing systemd architecture. The retired LXC is not production. The exact production hostname is `wohnwerk.lainlounge.org` and Caddy serves that explicit site without a wildcard/default site.

Current acquisition state:

1. `v0.4.0` Germany-capable runtime and migration `0012_de_postal_codes` are the production baseline;
2. 10,813 GeoNames DE postal centroids were imported while the Austria postal reference remained intact;
3. DE/AT country switching works on Houses, Jobs and `/admin/matches`;
4. refresh/images/liveness production timers are enabled and must remain enabled during source experiments;
5. ImmoScout24 is absent from the automatic scheduler while its transport is paused;
6. Immowelt is automatic **incremental/frontier only**, not reconciliation-authoritative;
7. Immowelt failures are source-isolated so they cannot make `wohnwerk-refresh.service` fail by themselves;
8. Immowelt challenge handling persists same-run state and uses the external handler boundary described above;
9. untouched shards after a source-wide halt are telemetry `skipped`, not fabricated failures;
10. Austria acquisition must continue independently of German source health.

## Recovery rule

Fresh context order:

1. `HANDOFF.md`;
2. this document;
3. `docs/acquisition.md`;
4. `docs/sources.md`;
5. frozen Austria compatibility baseline.

Do not reopen the generic debate "ToS means we cannot crawl". Follow the explicit public-frontend policy and red lines in this document, then continue implementation evidence-first.
