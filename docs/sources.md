# Austrian Source Candidates

Research snapshot: 2026-08-26

This document is a source-planning inventory, not a statement that automated extraction is permitted from every listed site. Before implementing each adapter, review the current public interface, available feeds/APIs, site terms, request characteristics, and the least intrusive acquisition path.

## Property sources

### P0 — willhaben Immobilien

URL: https://www.willhaben.at/iad/immobilien/

Why it matters:

- extremely large Austrian inventory;
- nationwide location filters;
- purchase-price and area filters;
- rich property-type taxonomy.

Important acquisition constraint: willhaben's current terms prohibit copying by robot/crawler or other automated mechanisms without prior permission. Do not implement a general-purpose crawler against the listing database.

Useful permitted-user workflow: willhaben provides saved-search agents with e-mail and app notifications for matching new listings. WohnWerk can ingest user-received alert data as a separate source channel, retaining the original listing link.

### P0 — ImmoScout24 Austria

URL: https://www.immobilienscout24.at/

Why it matters:

- Austrian nationwide coverage;
- dedicated house-purchase search;
- useful structured fields such as price, living area, location and many property attributes.

Important acquisition constraint: the current consumer terms explicitly prohibit automated queries by scripts, bots, crawlers, search software, data mining or data extraction unless permitted in writing.

Useful permitted-user workflow: ImmoScout24 provides saved-search agents that e-mail new matching listings. Treat these alerts as an acquisition channel instead of crawling the search database.

### P1 — immowelt.at

URL: https://www.immowelt.at/

Why it matters:

- Austrian property search by location or postal code;
- house/apartment purchase inventory;
- saved-search functionality with configurable e-mail notification intervals.

Adapter path: review current terms before any automated page acquisition. E-mail search alerts are a useful low-impact source regardless of whether a crawler is later appropriate.

### Later property candidates

Evaluate additional Austrian/regional portals, cooperative/open feeds, and direct brokerage sites after the first ingestion path establishes the common normalization contract. Prefer sources where automation is expressly available or at least not contractually prohibited. Regional sources can be valuable because nationwide portals do not necessarily contain every listing.

## Job sources

### P0 — AMS `alle jobs`

URL: https://www.ams.at/arbeitsuchende/arbeitslos-was-tun/jobsuche-online-und-mobil

Why it matters:

AMS describes `alle jobs` as a search engine covering free positions throughout Austria. Its result set combines several source classes, including:

- AMS-managed vacancies;
- AMS eJob-Room vacancies;
- vacancies found on websites of employers/institutions active in Austria;
- federal/state public administration vacancies;
- selected German Bundesagentur für Arbeit listings.

That aggregation makes AMS an unusually high-value job discovery source.

Important distinction: the documented AMS HR-API is an employer/recruiting-software interface for submitting vacancies to AMS, not a general public search API for downloading all vacancies. Do not mistake it for the acquisition interface we need.

Adapter path: investigate the current `alle jobs` search application and usage conditions before implementing local persistence.

### P0 — karriere.at

URL: https://www.karriere.at/

Why it matters:

- strong Austrian focus;
- many engineering/technical vacancies;
- useful location and compensation information;
- broad search terms such as Maschinenbau / Maschinenbauingenieur surface many adjacent roles, which is useful for our non-exact matching model.

Adapter path: source-specific investigation required before implementation.

### P1 — StepStone Austria

URL: https://www.stepstone.at/

Evaluate as an additional nationwide professional-job source after the first job adapter works end-to-end.

### P1 — willhaben Jobs

URL: https://www.willhaben.at/jobs/

Potentially useful as a user-notification source, but its general automated-acquisition restriction applies here too.

### P1/P2 — other job sources

Evaluate, among others:

- employer career pages;
- public-sector job portals;
- regional job boards;
- technically oriented recruitment sites;
- additional aggregators where they add genuinely new coverage rather than only duplicates.

## Austrian salary advantage

Austrian private-sector job advertisements are generally required to state the applicable minimum remuneration (collective-agreement/statutory minimum or a negotiation basis where no such minimum exists) and, where applicable, willingness to pay above that minimum.

Primary references used during design:

- Austrian government equal-treatment guidance
- Arbeiterkammer equal-treatment guidance

This makes advertised compensation unusually useful for automated job comparison, but the amount may be only a collective-agreement minimum rather than the likely final salary.

## 13th/14th salary caution

Do not automatically multiply every monthly salary advertisement by 14.

Holiday and Christmas special payments are common in Austria and are often governed by collective agreements, but there is no universal statutory entitlement in ordinary private employment when neither the applicable collective agreement nor the individual contract provides them.

The parser should preserve the raw compensation text and only derive an annual figure when the payment basis is sufficiently clear.

## Postal-code reference data

### P0 — RTR Austrian postal codes

Dataset: https://www.data.gv.at/datasets/f76ed887-00d6-450f-a158-9f8b1cbbeebf

Publisher: RTR-GmbH

License: CC BY 4.0

Use RTR as the canonical PLZ/name seed. `scripts/import_postal_codes.py` imports current addressable Austrian postal codes and deliberately preserves later geographic enrichment.

### P0 — BEV Adressregister Stichtagsdaten

Dataset: `Adresse Relationale Tabellen - Stichtagsdaten`

Publisher: Bundesamt für Eich- und Vermessungswesen (BEV)

License: CC BY 4.0

The free nationwide snapshot contains `ADRESSE.csv` with PLZ and one-metre geocoded address coordinates. The documented coordinate fields are `RW`, `HW`, and `EPSG`; supported Austrian Gauss-Krüger CRS values are EPSG:31254, 31255 and 31256.

WohnWerk does not need to retain millions of street addresses. `scripts/import_postal_centroids.py` streams `ADRESSE.csv`, aggregates addresses by PLZ and source CRS, transforms only the aggregate means to WGS84, and updates the existing RTR rows with an approximate address-weighted postal-code location. This keeps the database small while preserving enough geographic accuracy for 25/50/100/custom-km matching.

The resulting location is explicitly metadata-tagged as:

```text
location_source = BEV Adressregister Stichtagsdaten
location_method = address_mean
location_sample_count = number of geocoded address rows used
```

## Source adapter rules

Every source adapter should expose the same logical output and should own its own operational policy:

```text
name
enabled
poll_interval
request delay / jitter
pagination/search partitioning
last success
last error
```

General acquisition preference order:

```text
official/public API or feed
        ↓
provider-supported saved search / e-mail notification
        ↓
structured normal-user endpoint where permitted
        ↓
static HTML parsing where permitted
        ↓
browser automation where permitted
```

The source layer should behave conservatively: small concurrency, incremental discovery, backoff on errors/rate limits, and no repeated full-history requests when a newest-first incremental strategy can stop at already-known source IDs.
