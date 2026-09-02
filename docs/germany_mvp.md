# Germany MVP contract

**Status:** active development contract for `feature/germany`  
**Baseline:** frozen Austria v1 behavior remains the compatibility baseline  
**Scope:** Germany-oriented MVP implemented alongside Austria, not a replacement for the Austria release

This document records the product intent that must survive chat/context changes. It complements `HANDOFF.md`, `docs/requirements.md`, `docs/acquisition.md`, and `docs/sources.md`. Where older Austria-first documentation conflicts with the Germany-specific rules below, this document governs the Germany MVP.

## Goal

WohnWerk is a private/self-hosted application for finding suitable houses and suitable jobs and then matching the two geographically for the candidate/father.

The Germany MVP must make Germany a first-class country without changing the frozen Austria behavior. It is not a generic portal mirror and it must not republish third-party property portals.

The immediate Germany goal is:

1. acquire a high-recall but conservative index of German houses for sale inside the configured WohnWerk budget from acquisition paths whose terms/access model permit WohnWerk's automated use;
2. acquire relevant German jobs through legitimate public/supported sources;
3. keep German and Austrian acquisition/lifecycle state separated by source country;
4. expose the existing Häuser / Jobs / Matches product for either country through one simple country switch;
5. retain enough source facts for filtering, ranking, lifecycle checks and linking back to the original source without copying unnecessary content.

## Country model

Country scope is an acquisition/source property, not a duplicate geography flag on canonical `Property` or `Job` rows.

- source country comes from `Source.config["country_code"]`;
- legacy sources without country metadata are treated as `AT`;
- supported UI countries are `DE` and `AT`;
- country selection scopes father-facing `/houses`, `/jobs`, and `/admin/matches` reads;
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

The configured house-acquisition budget remains:

```text
EUR 30,000 .. 300,000
```

The existing Germany portal prototypes partition this range into deterministic, non-overlapping engineering shards:

```text
EUR 30,000..149,999
EUR 150,000..224,999
EUR 225,000..300,000
```

These internal boundaries are not product preferences or ranking weights. They exist only to bound result sets. They may be rebalanced for a future authorized source if observed result distributions justify it.

### Commercial-portal status as of 2026-09-02

`immoscout24-de` and `immowelt-de` adapters exist in the branch as acquisition prototypes, but **they are not approved/enabled production acquisition paths**.

- A target-host ImmoScout24 public-search probe returned HTTP `401 Unauthorized` on 2026-09-02.
- Current ImmoScout24 website AGB, section 8.2, prohibit automated queries by scripts/bots/crawlers and data extraction; section 8.3 also prohibits using queried data to build a separate database.
- Do not respond to the `401` by spoofing browser headers, adding cookies, automating login, switching to Playwright, solving challenges, proxying, or otherwise trying to make the crawler look like a normal human browser.
- Current ImmoScout24 Search API documentation says Search APIs are available only to content partners and not for data-delivery use cases. Any future ImmoScout integration therefore requires an explicit authorized use case/permission whose terms fit WohnWerk.
- AVIV/Immowelt published a text/data-mining reservation dated 2026-02-27 that expressly rejects automated collection/extraction. Do not run the existing Immowelt Playwright discovery prototype under the current assumptions.
- Immowelt does publish an official API, but its standard published usage terms are tied to provider/partner use (principally the provider's own objects, or explicitly approved marketplaces). Do not assume it authorizes a third-party whole-market mirror.

Official references to re-check before any future portal activation:

- ImmoScout24 website AGB: `https://www.immobilienscout24.de/agb/nutzungsagb.html`
- ImmoScout24 Search API introduction: `https://api.immobilienscout24.de/api-docs/search/introduction/`
- Immowelt DSA / data-mining notice: `https://www.immowelt.de/immoweltag/agb/dsa`
- Immowelt API terms: `https://www.immowelt.de/meineimmowelt/apinutzungsbedingungen.aspx`

## Acquisition and legal/operational guardrails

A page being publicly visible to a normal browser is not by itself authorization for WohnWerk to automate collection or build a persistent index from it.

For German property acquisition:

- use only an authorized API/feed/export or a public data source whose access/reuse model supports the intended automation;
- no user account/login automation unless the source explicitly authorizes the integration and credentials are supplied for that purpose;
- no bypass of access controls;
- no CAPTCHA solving;
- no stealth/anti-bot evasion;
- no browser-header or cookie spoofing intended to defeat protection;
- no proxy rotation or similar mechanism intended to defeat protection;
- no reverse-engineered private API merely as a shortcut around an interface or access policy;
- stop/fail closed when the source presents a challenge, access protection, or a policy mismatch;
- re-review source terms/access conditions before activation and when they change materially.

Prefer acquisition paths in this order where available:

```text
explicitly authorized official API / complete feed
        -> provider-authorized OpenImmo or comparable syndication feed
        -> other public/open dataset whose terms permit automated reuse
```

An OpenImmo URL is usable only when the feed owner provides or authorizes that feed. OpenImmo is a data format, not a blanket authorization to retrieve arbitrary private feeds.

The OpenImmo 1.x format itself remains usable and is widely intended for real-estate data exchange, so provider-authorized OpenImmo feeds are a strong candidate for Germany source expansion.

## Retention rules

Retention follows the source's authorization/terms and WohnWerk's minimum-necessary product needs.

For commercial source data where an authorized integration is eventually obtained, prefer retaining only:

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

Do not retain descriptions, contacts, photos or page snapshots unless the specific source/feed authorization permits them and the product actually needs them.

Never infer missing property facts without source evidence.

## Dormant portal prototype behavior

### ImmoScout24 Germany

Prototype code currently implements low-rate public HTML/context acquisition and deterministic 48-shard partitioning. It is retained for reference/testing but must not be activated against the live portal without a future authorized basis that permits the intended use.

The 2026-09-02 `401` is an access-policy stop signal, not a bug to bypass.

### Immowelt Germany

Prototype code currently implements ordinary Chromium-rendered search acquisition. Because the current published AVIV/Immowelt policy explicitly rejects automated data collection/extraction, this path is dormant and must not be activated merely because Chromium can render the page.

## Coverage and disappearance authority

Discovery success and disappearance authority are separate.

Incremental scans:

- request newest-first where supported;
- are optimized for discovering new/updated listings;
- may stop at a known/old frontier;
- never prove that an unseen listing disappeared.

A Germany property reconciliation may prove disappearance only for a source whose acquisition is authorized and when all required conditions hold:

1. every enabled shard ran;
2. every shard completed successfully;
3. every shard is fully traversed / `coverage_complete=true`;
4. no shard hit a result/page cap;
5. parsed identities are complete enough for the source policy;
6. observed unique IDs are plausible against source-reported counts/tolerances where such counts exist.

Anything partial, capped, challenged, parser-incomplete or otherwise degraded is non-authoritative and must not mass-deactivate listings.

Never manually promote `Source.coverage_status` to manufacture authority.

## Germany postal geography

Germany requires five-digit postal codes and uses migration `0012_de_postal_codes`.

GeoNames German postal-code data supplies Germany postal centroids for matching/location support. Germany data must not be pushed through Austria-specific PLZ/locality assumptions.

Target production bootstrap completed on 2026-09-02 with 10,813 GeoNames DE postal-code centroids; the Austria 2,234-row postal reference hash remained unchanged across the import. Treat those counts as observations rather than permanent invariants because upstream datasets may change.

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

The Germany runtime/geography foundation may be production-ready independently of any Germany property acquisition source.

Completed foundation gates on the target system include:

1. exact-head CI green;
2. runtime v0.4.0 with DE/AT country scope;
3. DB migration `0012_de_postal_codes`;
4. GeoNames DE postal import and AT-integrity verification;
5. DE five-digit/city radius resolution smoke;
6. Playwright Chromium runtime installation (available for sources that are actually authorized to require a browser).

Before any Germany property source becomes enabled/authoritative:

1. document an acquisition/reuse basis appropriate to that source;
2. exact-head CI must be green for the adapter actually being enabled;
3. run a bounded non-authoritative smoke;
4. inspect parser/field/provenance behavior;
5. run an incremental ingestion only after the smoke is healthy;
6. only then consider reconciliation;
7. a partial/degraded reconciliation remains non-authoritative.

`immoscout24-de` and `immowelt-de` do not currently pass gate 1 and therefore must remain dormant.

## Recovery rule

When a fresh context starts, read in this order:

1. `HANDOFF.md` for the exact operational checkpoint;
2. this file for Germany product/UI/acquisition intent;
3. `docs/acquisition.md` for coverage mechanics;
4. `docs/sources.md` for source-specific planning/evidence;
5. frozen Austria release behavior as the compatibility baseline.

Do not infer that an implemented adapter is authorized to run merely because its code/tests exist. Active development is the Germany-oriented MVP on `feature/germany` until `HANDOFF.md` says otherwise.
