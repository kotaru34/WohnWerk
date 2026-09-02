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

Do **not** treat a portal ToS as an automatic technical veto. For this private/self-hosted project, ToS is considered an operational/civil risk signal and source-specific constraint, while the crawler design remains governed by the concrete technical/legal red lines below.

Publicly reachable frontend pages may be acquired carefully when doing so does not require bypassing a technical access barrier. A plain HTTP client returning `401/403` does not by itself mean the public frontend is forbidden: an ordinary browser renderer may be used if the same page is normally available to an unauthenticated user.

Allowed engineering progression:

```text
normal public HTTP
    -> ordinary Chromium rendering when the public site requires browser execution
```

Red lines:

- no login/account automation for portal crawling;
- no CAPTCHA solving;
- no paywall/access-control bypass;
- no deliberate IP-ban bypass;
- no stealth/anti-bot frameworks intended to evade detection;
- no residential/proxy rotation intended to defeat blocking;
- no reverse-engineered private API solely to bypass the normal interface;
- no credential theft or reuse of private session material;
- no aggressive request rates;
- stop/fail closed on an explicit challenge or technical block rather than trying to defeat it.

Normal browser execution is **not** considered stealth by itself. Use stock Playwright/Chromium behavior without fingerprint-masking plugins or challenge bypasses.

Use conservative delays, caching where useful, and standard backoff for transient `429/5xx` responses.

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
- arbitrary page snapshots;
- invented/inferred attributes without source evidence.

This is a private matching index, not republication of the source database.

## ImmoScout24 Germany

Current adapter partitions Germany into the 48 shards above and parses public house-sale search results.

Target-host observation on 2026-09-02:

- plain `httpx` request to `Sachsen / EUR 30k..149,999` returned HTTP `401`;
- this is treated as a transport/interface result, not as an automatic project veto;
- next implementation step is ordinary stock Chromium rendering of the same unauthenticated public search page;
- do not add stealth plugins, login, CAPTCHA handling, private cookies or proxy evasion.

Search/list-result acquisition is preferred over unnecessary detail-page crawling. Incrementals are newest-first where supported.

## Immowelt Germany

The adapter uses ordinary Playwright Chromium public-search rendering. Do not open listing detail pages during normal discovery. Heavy image/media/font resources may be suppressed to avoid needless transfer. Page 250 remains a hard safety cap. CAPTCHA/challenge/access protection stops that crawl path rather than being solved.

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
6. observed unique IDs are plausible against source-reported counts/tolerances where available.

Partial, capped, challenged, parser-incomplete or degraded runs are non-authoritative. Never manually promote `Source.coverage_status`.

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

Completed on the target system:

1. `v0.4.0` Germany-capable runtime deployed;
2. DB at `0012_de_postal_codes`;
3. 10,813 GeoNames DE postal centroids imported;
4. AT postal integrity preserved;
5. DE 5-digit and city radius resolution smoke passed;
6. stock Playwright Chromium installed and launches as `www-data`;
7. DE/AT country switch works on Houses, Jobs and `/admin/matches`;
8. refresh/images/liveness timers intentionally remain stopped while Germany acquisition is validated.

Current property acquisition checkpoint:

- ImmoScout plain-HTTP single-shard probe returned `401` before any DB mutation;
- no ImmoScout source/listings/runs were created by that read-only probe;
- next step is a read-only single-shard stock-Chromium ImmoScout smoke;
- if healthy, proceed to bounded incremental ingestion;
- validate Immowelt similarly after ImmoScout.

## Recovery rule

Fresh context order:

1. `HANDOFF.md`;
2. this document;
3. `docs/acquisition.md`;
4. `docs/sources.md`;
5. frozen Austria compatibility baseline.

Do not reopen the generic debate "ToS means we cannot crawl". Follow the explicit public-frontend policy and red lines in this document, then continue implementation evidence-first.