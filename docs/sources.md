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

### Germany public portal and broker layer

The deployed v0.4.9 release broadens Germany house discovery, and v0.4.10 adds a
second independent broker frontier while keeping each source's coverage authority explicit:

- `immowelt-de`: existing broad public portal, incremental/frontier-only in the
  automatic scheduler while browser/challenge behavior remains under observation;
- `immoscout24-de`: existing 48-shard public search adapter, now with explicit
  browser-challenge detection, persisted storage-state handoff and same-run resume;
  it remains unscheduled until the production transport is revalidated;
- `kleinanzeigen-de`: bounded newest-first public house frontier. Its nationwide
  corpus is much larger than the bounded scan, so it **never** gains disappearance
  authority from that frontier;
- `von-poll-de`: adapter retained for diagnostics, but the production source is
  disabled fail-closed after sequential live access reached HTTP 403; it must not be
  treated as operational coverage until a supported transport is validated;
- `engel-voelkers-de`: v0.4.10 bounded newest-first frontier over the public
  Germany house corpus. Public expose UUIDs provide stable source identity and
  detail pages expose structured energy-source fields. The frontier never claims
  disappearance authority.
- `remax-de`: v0.4.12 adapter retained for diagnostics, but **not scheduled in
  production**. Target-host live validation on 2026-10-03 returned a Cloudflare
  Turnstile `Security Verification` page instead of listing HTML. The adapter
  explicitly detects that challenge and halts fail-closed; WohnWerk does not solve,
  replay or bypass it. Public-browser observations remain useful for future transport
  revalidation, but RE/MAX contributes no operational production coverage in this release.
- `iad-de`: v0.4.12 operational direct iad Immobilien Agentur Deutschland
  broker-network frontier over bounded nationwide house pages. Target-host validation
  confirmed raw listing HTML is directly available (932 houses observed during the
  release gate). The public detail slug carries a stable object identifier; WohnWerk
  retains that provenance plus card-backed location/price/area/preview facts. iad may
  syndicate listings to large portals, so canonical dedupe remains conservative and
  source provenance remains distinct.

The active Germany purchase budget is EUR 30,000..200,000. Discovery adapters keep
source identity/URL, title, asking price, explicit living/plot area, PLZ/city and
bounded source-backed enrichment. Full descriptions, seller/broker contact data and
portal-hosted photos are not retained as catalogue data.

`immonet.de` is not represented as an independent WohnWerk source: its current
public web entry redirects into Immowelt. Treating it as a separate source would
manufacture duplicate provenance for the same inventory rather than add an
independent acquisition layer.

Incremental/frontier scans discover and update but never prove disappearance.
Reconciliation is authoritative only when the source adapter proves complete
coverage, every shard/page/card identity parses, no cap is hit and the normal count
plausibility checks pass.

Cross-source duplicate handling is deliberately conservative. Source listings remain
separate provenance records underneath a canonical property; a merge requires
compatible PLZ, asking price and corroborating area/title evidence, and ambiguous
multi-candidate matches fail closed.

For sources such as Engel & Völkers whose public result cards expose municipality but
not PLZ, WohnWerk may resolve a missing German PLZ from the local postal reference
only when that municipality maps to exactly one five-digit code. Multi-PLZ cities stay
unresolved; no postcode is guessed.

Heating enrichment stores only normalized source-backed heating types and short
energy-field evidence snippets. Unknown stays unknown. `Holz` is surfaced as the
configured positive preference; WohnWerk does not infer wood heating from unrelated
listing prose.

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


## Fixed Internet reference data

For Germany, WohnWerk v0.4.6 uses the official Bundesnetzagentur
Breitbandatlas / Gigabit-Grundbuch fixed-network grid export. The pinned candidate
snapshot is **2025-12-31**. The public dataset is a 100 x 100 m raster and reports
the percentage of households in each cell covered by each download-speed class
and technology combination. Those percentages are area evidence, not an
address-level orderability promise.

WohnWerk therefore never maps the public grid to a house from a PLZ centroid.
Only an explicitly source-backed/address-backed point with sufficiently precise
location provenance may enter a 100 m cell lookup. A speed class counts as a
defensible cell-wide floor only when the source reports 100% household coverage
for that cell. Partial coverage remains visible as a percentage and is never
promoted to house availability.

Starlink is an explicit fallback/check path rather than assumed availability.
When the configured fixed-network target cannot be established from defensible
house evidence, WohnWerk may show the current source-backed Starlink reference
offer and a link for an address-specific check. Price, capacity and availability
must still be confirmed for the concrete address.

Required German attribution for the imported grid:
`Breitbandatlas | Gigabit-Grundbuch (https://gigabitgrundbuch.bund.de)`.

### DE portal/detail Internet evidence

WohnWerk v0.4.8 adds a second, deliberately separate evidence layer from German
listing/detail pages. It never replaces the official Breitbandatlas grid and it is
not promoted to a contractual line-speed claim.

Observed ImmoScout24 DE detail pages expose a structured Telekom-backed Internet
availability/speed estimate and describe the displayed speed as a non-binding
estimate based on the listing's Standortadresse; binding availability is deferred
to an actual order/check. Some details also expose explicit street + house number
metadata. WohnWerk stores those values as `portal_address_estimate` and
`street_house_number` source evidence respectively. A source address is still
not a coordinate and must not enter a 100 m Breitbandatlas lookup until a separate
geocoding step establishes defensible coordinate provenance.

Observed Immowelt DE exposés may state provider/technology/speed facts directly in
the listing text, for example Telekom DSL, Vodafone Kabel or M-Net Glasfaser with
an explicit Mbit/s value. WohnWerk stores those statements as `listing_claim`.
They remain "Angabe im Exposé": useful source evidence, but not an independent
provider orderability test. Explicit "connected", "at property" or "planned"
Glasfaser statements can also be retained without inventing a speed.

The UI must preserve the evidence class visibly:
- `Portal-Schätzung` for address-based portal estimates;
- `Angabe im Exposé` for listing statements;
- `Amtliches Raster` for the official 100 x 100 m Bundesnetzagentur cell.

The bounded Immowelt detail worker uses the normal project browser transport and
existing challenge detection only. It stops on a detected challenge and never
invokes the operator-owned external challenge handler. It is deliberately not
wired into the automatic refresh loop in v0.4.8; deployment/maintenance runs it
in bounded batches so source pressure and challenge behaviour can be observed
before any recurring cadence is introduced. ImmoScout24 DE detail fetching
remains dormant while that source is paused; only parser/schema support is
present in v0.4.8.

## German hospital access

WohnWerk uses the official Bundes-Klinik-Atlas Open Data export as the authoritative
Germany hospital-access dataset. The imported TVERZ snapshot supplies hospital-site identity,
address, coordinates and explicit emergency-care fields. WohnWerk does not infer emergency
capability from a generic hospital name or category.

The current v0.4.5 importer is pinned to the 2026-09-01 export and records the dataset date and
source URL. Publication is snapshot-atomic: stale rows are reconciled only after the complete
archive has parsed successfully, and only a complete published snapshot receives
`coverage_status=ok`.

For suitability, a usable emergency site must have an explicitly agreed Notfallstufe 1, 2 or 3.
Additional fields such as Schwerverletztenversorgung, Kinder-Notfallstufe, Spezialversorgung,
Stroke Unit and Chest Pain Unit remain separate source-backed facts. Missing capability stays
unknown.
