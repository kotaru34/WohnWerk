# Coverage-first acquisition

WohnWerk optimizes for recall: it should miss as few publicly available suitable homes and jobs as practical.

## Alerts are supplemental

Saved-search e-mail notifications and portal push alerts can reduce discovery latency, but they are not authoritative inventory sources. A source is considered covered only when WohnWerk can independently account for its search space or receives an explicitly complete feed/export.

## Crawl cycle model

A `crawl_run` is one source-level cycle. Each configured `source_shard` receives one `crawl_shard_run` within that cycle.

A reconciliation cycle may deactivate previously active listings only when:

1. every enabled shard ran;
2. every shard completed successfully;
3. every shard reports `coverage_complete=true`;
4. no shard reports `result_cap_hit=true`.

Anything less is `DEGRADED` coverage and is never allowed to mass-deactivate listings.

## Sharding

Source-specific shards keep each search safely below portal result caps and pagination ceilings. Shards should begin with the largest stable geographical partition supported by the source and split only as needed.

Typical property hierarchy:

```text
Austria
  -> Bundesland
  -> Bezirk / PLZ group
  -> price range when necessary
  -> property subtype when necessary
```

The Germany portal adapters use a fixed, deterministic equivalent:

```text
Germany
  -> 16 states/city-states
  -> EUR 30,000..149,999 / 150,000..224,999 / 225,000..300,000
```

The bands are non-overlapping and match the existing WohnWerk house budget. `immowelt-de` treats
page 250 as a hard cap; either adapter reports capped/degraded coverage if a shard reaches its
safety ceiling. Both request newest-first for incrementals and require count-plausible exhaustive
coverage for reconciliation.

A shard whose reported result count approaches or reaches a known source cap must be split before it can be considered fully covered.

## Incremental scans

Incremental scans are optimized for discovery latency and low external load:

- request newest-first where the source supports it;
- stop after reaching a sufficiently old/known frontier;
- persist source-specific cursor state;
- do not infer disappearance from an incremental scan.

## Full reconciliation

Reconciliation periodically scans the complete configured source search space. Listings seen in the completed cycle receive the current `crawl_run` id. Only after source-level coverage is `OK` may source listings not seen in that run be marked inactive.

## Multi-source coverage

No single portal is assumed to represent either market. Property coverage should combine large portals, regional portals, direct broker websites, broker-network sites, and authorized structured feeds/APIs. Job coverage should combine aggregators, professional job boards, public-sector sources and direct employer career pages.

Cross-source duplicates remain separate source listings underneath one eventual canonical property/job entity.

## OpenImmo

OpenImmo is a common real-estate exchange format used by Austrian broker software and portals. WohnWerk includes a generic full-feed OpenImmo adapter for XML/ZIP exports that are provided to WohnWerk or otherwise intended for automated import. A complete OpenImmo export is especially useful because it can support deterministic reconciliation without pagination caps.

The existence of the OpenImmo format does not itself grant access to a broker's private feed; feed access is configured per source.

## Resource policy

The application container has enough CPU for local parsing, normalization and reconciliation. External request concurrency remains deliberately conservative. Extra CPU should be spent processing already acquired data rather than increasing request pressure on third-party services.
