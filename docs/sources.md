# Austrian Source Candidates

Research snapshot updated: 2026-08-27

This is a source-planning inventory, not a statement that every acquisition method is permitted for every site. WohnWerk is coverage-first: alerts may supplement discovery, but they are not authoritative inventory sources. Each source gets its own adapter and operational policy.

See `docs/acquisition.md` for shard, incremental scan, cap detection and reconciliation rules.

## Property acquisition layers

WohnWerk should combine independent layers rather than depend on one portal:

1. a high-recall public meta-search discovery layer;
2. large Austrian portals where a suitable acquisition path exists;
3. regional portals;
4. direct broker and broker-network sites;
5. structured broker feeds and APIs (OpenImmo, Justimmo and similar) where access is available;
6. saved-search notifications only as a supplemental low-latency signal.

Cross-source duplicates remain distinct source listings underneath a later canonical property entity.

### Germany public portal layer

`immoscout24-de` and `immowelt-de` cover public German house-for-sale search pages inside the
WohnWerk EUR 30,000..300,000 product budget. Each adapter uses 48 deterministic shards: all 16
states/city-states crossed with three non-overlapping price bands. Live validation on the largest
state kept those bands below the portals' safety ceilings.

Both adapters keep only source ID/URL, title, price, living/plot area, PLZ and city. Descriptions,
contact data and photos are not retained. ImmoScout24 is acquired through low-rate HTML requests.
Immowelt requires ordinary browser rendering; it blocks heavy image/media/font resources, does not
open detail pages, and stops rather than solving a CAPTCHA or access challenge.

Incremental scans use newest-first ordering and never prove disappearance. A reconciliation is
authoritative only when every shard is fully traversed, every card identity parses, observed unique
IDs remain within the documented count tolerance and no shard reaches its cap.

### IMMMO meta-search discovery

`immmo.at` is a live Austrian meta-search engine for third-party property offers. Its public house-for-sale result pages expose enough discovery metadata to retain a minimal local index: title, original external listing URL, price, PLZ/city and living area, with plot area sometimes recoverable from the visible result snippet.

The Austria-wide `Haus-kaufen` result is larger than the site's visible 12,000-result boundary, so WohnWerk must never treat that single search as complete. The adapter partitions discovery by all nine Bundeslaender. Current state-level result counts fit below the page ceiling and can therefore be reconciled independently.

WohnWerk treats IMMMO as a discovery index rather than republishing it: it stores normalized metadata and the original third-party URL, not a local copy of IMMMO descriptions. Its current Nutzungsbedingungen prohibit abusive, commercial and republication uses but do not state a general prohibition on automated access. The WohnWerk adapter remains low-rate and private/self-hosted; source terms must be re-reviewed if the deployment model changes.

Operational safeguards specific to this adapter:

- all nine Bundesland shards must complete for authoritative reconciliation;
- off-domain redirects are failures rather than empty successful scans;
- a missing result count or zero parsed cards on a non-empty result page is a failure;
- a lower-bound/capped result count is `DEGRADED` and cannot reconcile;
- reconciliation checks parsed unique-listing count against the source-reported count;
- only minimal discovery metadata is retained.

### Retired / unsuitable discovery sources

`immoads.at` was evaluated and an adapter prototype was tested on 2026-08-26. A live smoke run returned zero listings because the former property routes now redirect to `oe24.at`; older ImmoAds property/search pages visible in search-engine caches are stale. The adapter was removed rather than kept as misleading dead code. The failed/partial crawl run may remain in the production crawl history as an audit record, but the `immoads.at` source should be disabled.

IMMOunited is useful as a market-size/coverage benchmark, but its current terms explicitly prohibit automated bot/script access and automated crawling/scraping/caching, so it is not a direct WohnWerk crawler backend without separate authorization.

### Large portals

High-priority coverage targets include:

- willhaben Immobilien;
- ImmoScout24 Austria;
- immowelt.at.

These sources are valuable because of their national inventory, but their adapters must respect the acquisition mechanisms actually available to WohnWerk. WohnWerk must not silently substitute a limited e-mail alert stream for full source coverage.

When a source has a result cap or pagination ceiling, partition the search space into geographical and, when required, price/property-type shards until every shard can be completely traversed.

### Regional portals

Regional sources can contain inventory absent from national portals and are therefore first-class sources, not merely backups.

One concrete candidate is `laendleimmo.at`, focused on Vorarlberg and offering detailed house, plot-area, living-area, price and recency filters through its normal search interface. Source-specific access rules still need review before an adapter is enabled.

### Broker and upstream structured feeds

OpenImmo is widely used as the real-estate exchange format between broker software and Austrian portals. WohnWerk now has a generic XML/ZIP OpenImmo full-feed adapter.

A full feed is particularly valuable because it supports deterministic reconciliation without pagination caps. Feed access remains source-specific: the existence of OpenImmo as a format does not grant access to a broker's private export.

Justimmo documents both HTTP APIs and full FTP exports in OpenImmo and related formats. Its realty API supports list/search/detail operations, while full feeds can transfer the complete set of booked realties. These are strong candidates when a broker or partner authorizes WohnWerk access.

## Job acquisition layers

Job coverage should combine structured public employer feeds/APIs, public-sector sources and additional legitimate independent sources. No one employer ATS is a nationwide anchor by itself, so coverage must be composed from many independent shards/sources.

### Lever Public Postings API — first live structured layer

Lever documents a public Postings API for published vacancies. Published jobs are publicly viewable, the API exposes paginated JSON, and Lever's own documentation explicitly notes that published postings may be scraped by third parties. The API has separate global and EU instances.

WohnWerk therefore treats explicitly configured Lever tenants as legitimate structured source shards. The adapter:

- scans one tenant per shard;
- uses stable Lever posting IDs;
- traverses pagination to a short final page for authoritative reconciliation;
- retains only postings whose location is demonstrably Austrian;
- preserves title, employer, descriptions, source URL, workplace type and structured salary information where exposed;
- never assumes a monthly salary implies 14 annual payments;
- reports a safety-page ceiling as incomplete/capped coverage rather than silently succeeding.

Initial tenant seeds are deliberately modest and can be expanded as Austrian employers using Lever are identified:

- Blackshark.ai (EU Lever instance);
- Westernacher Consulting (EU Lever instance);
- cargo-partner (global Lever instance);
- Qualysoft (global Lever instance);
- TSMG (global Lever instance).

This source is **not** equivalent to an Austria-wide job board. Its value is that each configured employer feed is complete, structured and independently reconcilable.

### AMS `alle jobs` — discovery reference, not a crawler backend

AMS `alle jobs` remains valuable as a high-recall reference because it combines AMS vacancies, eJob-Room, internet-discovered vacancies, public administration and selected neighbouring-country data.

However, the current AMS terms for `alle jobs` explicitly restrict use to a person's own manual job search and prohibit automated mechanisms for using listed job data for one's own purposes. WohnWerk must therefore **not** implement a direct `alle jobs` crawler or private API reverse-engineering path without separate permission or a newly documented supported feed/API.

AMS can still inform product/search design conceptually. Its documented search behaviour is itself a useful reminder that high recall requires more than exact title matching: AMS considers text frequency, word parts, spelling similarity, stemming/derivation and German normalization.

### AMS occupational/skills taxonomy

AMS occupational information remains an attractive future vocabulary/reference layer for WohnWerk's adaptive title/skill discovery. It can help normalize related occupations, competencies and titles instead of maintaining one brittle hand-written keyword list.

Before automated ingestion is implemented, the exact supported machine-readable access and reuse terms for the relevant AMS taxonomy/data product must be confirmed. Until then, WohnWerk's runtime discovery should rely on vacancy-corpus extraction plus locally curated aliases/weights rather than silently crawling the AMS taxonomy.

### EURES

EURES is useful as a coverage/reference service, but it is not currently assumed to be a public bulk vacancy API for WohnWerk. Any EURES-backed acquisition must use an explicitly permitted interface and access model; do not screen-scrape or reverse-engineer it as a shortcut.

### Austrian public-sector sources

Official public-sector publication channels are valuable because they can contain technical vacancies absent from commercial boards.

EVI (`evi.gv.at`) publishes Bundesdienst and related official notices, including vacancy notices with fields such as service location, employment type, application deadline and, in some notices, salary information. It is a promising independent public-sector layer.

Before enabling an automated EVI adapter, WohnWerk must confirm an appropriate machine-readable/reuse path and its terms. A public web page alone is not treated as permission for bulk automated acquisition.

### Additional structured employer feeds

Many Austrian employers use ATS platforms with structured published-job feeds. These can become additional independent layers when the platform's public interface and reuse semantics support it.

Candidates include:

- Personio public career-site XML feeds;
- Greenhouse public job-board endpoints;
- Ashby public job-board endpoints;
- other documented employer ATS feeds;
- direct company career APIs/feeds where explicitly public/supported.

Platform availability does not make every tenant automatically relevant; WohnWerk should add Austrian employers deliberately and keep one tenant/employer as an independently diagnosable acquisition shard where practical.

### Conventional job boards

Coverage candidates still worth separate source-by-source review include:

- karriere.at;
- StepStone Austria;
- willhaben Jobs;
- jobs.at;
- hokify;
- engineering and technical recruitment sites.

Queries and ranking must cover adjacent mechanical-engineering roles rather than one exact title. Candidate generation and local ranking remain separate steps.

## Adaptive job vocabulary

WohnWerk must not depend on a static list such as `Maschinenbauingenieur` alone.

As real vacancies arrive, the system should discover related job titles, skills, tools and role-family concepts from the corpus. These automatically discovered concepts are later presented in `Profil / Skills`, where the user assigns suitability/experience/preference weights. Unknown/unreviewed concepts remain neutral.

The intrinsic `job_fit_score` is recomputed from vacancy features plus the current user profile. It remains independent of geography. House/job pair recommendations then combine intrinsic job fit, property suitability and configured distance constraints without destroying the underlying component scores.

## Austrian compensation data

Austrian private-sector job advertisements are generally required to state the applicable minimum remuneration and, where applicable, willingness to pay above that minimum.

Advertised amounts may be collective-agreement minima rather than expected final salaries, so WohnWerk preserves raw salary text and provenance alongside normalized figures.

Do not automatically multiply every monthly salary advertisement by 14. Special payments are common but their exact entitlement/basis depends on the applicable collective agreement or contract. Annualization may use a payment count only when the source makes that dimension explicit or otherwise supplies sufficiently reliable semantics.

## Postal-code reference data

RTR is the canonical source for Austrian PLZ/name data. BEV Adressregister data supplies the geocoded address samples from which WohnWerk derives approximate PLZ centroids for PostGIS matching.

The production database already contains the Austria-first schema, RTR PLZ data and BEV-derived PLZ geography.

## Operational source rules

Every source owns:

```text
name
enabled
adapter
poll interval
source shards
result cap / cap detection
cursor/frontier state
last incremental scan
last successful reconciliation
coverage status
last error
```

General acquisition preference order:

```text
authorized official/public API or complete feed
        ↓
structured normal-user endpoint suitable for automation
        ↓
static HTTP acquisition
        ↓
normal browser automation where appropriate
```

External request concurrency remains conservative. Extra local CPU is spent on parsing, normalization, deduplication and reconciliation rather than increasing request pressure.
