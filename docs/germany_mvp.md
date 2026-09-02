# Germany MVP contract

**Status:** active development contract for `feature/germany`  
**Baseline:** frozen Austria v1 behavior remains the compatibility baseline  
**Scope:** Germany-oriented MVP implemented alongside Austria, not a replacement for the Austria release

This document records the product intent that must survive chat/context changes. It complements `HANDOFF.md`, `docs/requirements.md`, `docs/acquisition.md`, and `docs/sources.md`. Where older Austria-first documentation conflicts with the Germany-specific rules below, this document governs the Germany MVP.

## Goal

WohnWerk is a private/self-hosted application for finding suitable houses and suitable jobs and then matching the two geographically for the candidate/father.

The Germany MVP must make Germany a first-class country without changing the frozen Austria behavior. It is not a generic portal mirror and it must not republish third-party property portals.

The immediate Germany goal is:

1. acquire a high-recall but conservative index of German houses for sale inside the configured WohnWerk budget;
2. acquire relevant German jobs through legitimate public/supported sources;
3. keep German and Austrian acquisition/lifecycle state separated by source country;
4. expose the existing Häuser / Jobs / Matches product for either country through one simple country switch;
5. retain enough source facts for filtering, ranking, lifecycle checks and linking back to the original source without copying unnecessary portal content.

## Country model

Country scope is an acquisition/source property, not a duplicate geography flag on canonical `Property` or `Job` rows.

- source country comes from `Source.config["country_code"]`;
- legacy sources without country metadata are treated as `AT`;
- supported UI countries are `DE` and `AT`;
- country selection scopes father-facing `/houses`, `/jobs`, and `/matches` reads;
- one canonical entity may still have source listings from more than one source where identity logic supports it;
- Germany-specific logic must never cause the Austria-only locality resolver or other Austria-specific assumptions to mutate German records.

## UI / UX intent

The father-facing UI remains German-only.

The Germany MVP uses the existing product rather than creating a second Germany site. The primary interaction is a compact persistent country selector for Germany and Austria. The current implementation is a small `DE / AT` switch that persists the choice in a cookie and preserves the current page/query context.

The switch applies to the three country-scoped product surfaces:

- `Häuser`;
- `Jobs`;
- `Matching`.

The UX goal is that changing country feels like changing the active market, not navigating to a separate application. Existing filtering, curation, favorites/hidden/viewed state, job-fit semantics and matching presentation should remain familiar across both countries unless a country-specific data rule requires otherwise.

Do not expose crawler/legal implementation details to the father-facing UI. Source links must remain visible so the original listing can be opened on the publisher's site.

## Germany property product scope

Current public portal layer:

- `immoscout24-de`;
- `immowelt-de`.

Current house acquisition budget for these adapters:

```text
EUR 30,000 .. 300,000
```

Both adapters use 48 deterministic shards:

```text
Germany
  -> 16 states / city-states
  -> EUR 30,000..149,999
  -> EUR 150,000..224,999
  -> EUR 225,000..300,000
```

The bands are non-overlapping. If a portal cap or count behavior makes a shard non-exhaustive, the shard must fail closed or be split; it must never be silently treated as complete.

## Public-site acquisition and legal/operational guardrails

The Germany portal adapters are deliberately conservative. This is an engineering policy, not a claim that every public page grants unrestricted reuse.

For German commercial property portals:

- use public pages only;
- no user account/login automation;
- no bypass of access controls;
- no CAPTCHA solving;
- no stealth/anti-bot evasion;
- no proxy rotation or similar mechanism intended to defeat protection;
- no reverse-engineered private API merely as a shortcut around the public interface;
- keep external request rates conservative;
- stop/fail closed when the source presents a challenge or access protection;
- source terms/access conditions must be re-reviewed if the deployment model or acquisition method changes materially.

Prefer acquisition paths in this order where available:

```text
authorized official/public API or complete feed
        -> structured normal-user endpoint suitable for automation
        -> static public HTTP acquisition
        -> ordinary browser rendering where needed
```

An OpenImmo URL is usable only when the feed owner provides or authorizes that feed. The existence of the OpenImmo format alone does not authorize access to a private feed.

## Minimal-retention rule for German commercial property portals

For `immoscout24-de` and `immowelt-de`, retain only the minimum facts needed by WohnWerk:

- source name;
- source listing ID;
- original/source URL;
- title;
- asking price;
- explicit living area when exposed;
- explicit plot area when exposed;
- PLZ;
- city/locality;
- first/last-seen and lifecycle/provenance metadata needed internally.

Do **not** retain from these portal adapters:

- listing descriptions/body text;
- broker/seller contact details;
- portal-hosted photos or a local photo mirror;
- arbitrary page snapshots intended to reproduce the listing;
- data inferred without source evidence.

The purpose is a private discovery/index layer that points the user back to the original portal, not republication of the portal's listing page.

This Germany-specific minimal-retention rule overrides older generic property requirements that allow descriptions/images where available. Those broader fields may still be valid for sources/feeds whose access and reuse model explicitly supports them.

## Portal-specific acquisition behavior

### ImmoScout24 Germany

- ordinary low-rate public HTML/context acquisition;
- search/list-result scope rather than unnecessary detail-page crawling;
- newest-first incrementals where supported;
- parser or access anomalies fail closed;
- no protection bypass.

### Immowelt Germany

- ordinary Chromium-rendered public search;
- heavy image/media/font resources may be blocked to reduce unnecessary transfer;
- do not open listing detail pages for the normal discovery crawl;
- page 250 is a hard safety cap;
- CAPTCHA/challenge/access protection terminates the affected crawl path rather than being solved or bypassed;
- matching Playwright Chromium runtime must be installed on the target host before enabling the source.

## Coverage and disappearance authority

Discovery success and disappearance authority are separate.

Incremental scans:

- request newest-first where supported;
- are optimized for discovering new/updated listings;
- may stop at a known/old frontier;
- never prove that an unseen listing disappeared.

A Germany property reconciliation may prove disappearance only when all required conditions hold:

1. every enabled shard ran;
2. every shard completed successfully;
3. every shard is fully traversed / `coverage_complete=true`;
4. no shard hit a result/page cap;
5. parsed card identities are complete enough for the adapter's policy;
6. observed unique IDs are plausible against source-reported counts/tolerances.

Anything partial, capped, challenged, parser-incomplete or otherwise degraded is non-authoritative and must not mass-deactivate listings.

Never manually promote `Source.coverage_status` to manufacture authority.

## Germany postal geography

Germany requires five-digit postal codes and uses migration `0012_de_postal_codes`.

GeoNames German postal-code data supplies Germany postal centroids for matching/location support. Germany data must not be pushed through Austria-specific PLZ/locality assumptions.

## Germany jobs

Initial Germany job acquisition paths include:

- Bundesagentur Jobsuche public source, without requiring a user account;
- Adzuna Germany API when credentials are configured;
- authorized German OpenImmo is property-only and must not be conflated with job acquisition;
- existing supported public employer/ATS mechanisms may be expanded to German employers when the interface and source semantics justify it.

Generic source expansion is not the immediate goal. Preserve the existing separation between broad discovery relevance, candidate fit, salary provenance, lifecycle and geography.

The intrinsic `job_fit_score` remains geography-independent. Country filtering and house/job distance are separate dimensions.

## Data truth rules

Across the Germany MVP:

- never invent coordinates;
- never invent price or salary semantics;
- never invent property attributes;
- only explicit living-area evidence maps to living area;
- only explicit plot/land-area evidence maps to plot area;
- generic/ambiguous area values must not be promoted to a more specific semantic field;
- source-backed provenance must remain inspectable;
- cross-source deduplication stays conservative;
- failed acquisition must not destroy previously valid user curation state.

## Rollout gate

The Germany branch is not production-authoritative merely because tests pass.

Before Germany property sources gain reconciliation/disappearance authority on the target system:

1. exact-head CI must be green;
2. target DB must be at `0012_de_postal_codes`;
3. German GeoNames postal centroids must be imported and sanity-checked;
4. matching Playwright Chromium must be installed for `immowelt-de`;
5. one manual incremental smoke must be run for each DE property source;
6. inspect shard failures, cap hits, source counts, parsed counts and representative PLZ/price/living-area/plot-area records;
7. only after a healthy incremental smoke may the first reconciliation be attempted;
8. a partial/degraded first reconciliation remains non-authoritative.

## Recovery rule

When a fresh context starts, read in this order:

1. `HANDOFF.md` for the exact operational checkpoint;
2. this file for Germany product/UI/acquisition intent;
3. `docs/acquisition.md` for coverage mechanics;
4. `docs/sources.md` for source-specific planning/evidence;
5. frozen Austria release behavior as the compatibility baseline.

Do not infer the active task from the currently deployed Austria production version. Active development is the Germany-oriented MVP on `feature/germany` until `HANDOFF.md` says otherwise.
