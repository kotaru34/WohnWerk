# Austrian Source Candidates

Research snapshot updated: 2026-08-26

This is a source-planning inventory, not a statement that every acquisition method is permitted for every site. WohnWerk is coverage-first: alerts may supplement discovery, but they are not authoritative inventory sources. Each source gets its own adapter and operational policy.

See `docs/acquisition.md` for shard, incremental scan, cap detection and reconciliation rules.

## Property acquisition layers

WohnWerk should combine independent layers rather than depend on one portal:

1. large Austrian portals;
2. regional portals;
3. direct broker and broker-network sites;
4. structured broker feeds and APIs (OpenImmo, Justimmo and similar) where access is available;
5. saved-search notifications only as a supplemental low-latency signal.

Cross-source duplicates remain distinct source listings underneath a later canonical property entity.

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

Job coverage should combine aggregators, professional job boards and direct employers.

### AMS `alle jobs`

AMS describes `alle jobs` as a search engine covering free positions throughout Austria. Its result set combines several source classes, including:

- AMS-managed vacancies;
- AMS eJob-Room vacancies;
- vacancies discovered on websites of employers/institutions active in Austria;
- federal/state public administration vacancies;
- selected German Bundesagentur für Arbeit listings.

That makes AMS a high-recall anchor, but it is not assumed to be an unrestricted public bulk-download API. The adapter must use a suitable supported/public acquisition path.

### Additional job sources

Coverage candidates include:

- karriere.at;
- StepStone Austria;
- willhaben Jobs;
- jobs.at;
- hokify;
- employer career pages;
- public-sector portals;
- engineering and technical recruitment sites.

Queries must cover adjacent mechanical-engineering roles rather than one exact title. Candidate generation and local ranking remain separate steps.

## Austrian compensation data

Austrian private-sector job advertisements are generally required to state the applicable minimum remuneration and, where applicable, willingness to pay above that minimum.

Advertised amounts may be collective-agreement minima rather than expected final salaries, so WohnWerk preserves raw salary text and provenance alongside normalized figures.

Do not automatically multiply every monthly salary advertisement by 14. Special payments are common but their exact entitlement/basis depends on the applicable collective agreement or contract.

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
