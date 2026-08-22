# Austrian Source Candidates

Research snapshot: 2026-08-22

This document is a source-planning inventory, not a statement that automated extraction is permitted from every listed site. Before implementing each adapter, review the current public interface, available feeds/APIs, site terms, request characteristics, and the least intrusive acquisition path.

## Property sources

### P0 — willhaben Immobilien

URL: https://www.willhaben.at/iad/immobilien/

Why it matters:

- extremely large Austrian inventory;
- nationwide location filters;
- purchase-price and area filters;
- rich property-type taxonomy including Einfamilienhaus, Bauernhaus, Bungalow, Doppelhaushälfte, Landhaus, Mehrfamilienhaus, Reihenhaus, Villa and others.

Current observed scale during research: more than 110,000 total real-estate advertisements on the platform.

Adapter path: **TBD after source-specific investigation**. Prefer a structured/public request path if one is available and suitable; otherwise evaluate ordinary browser-driven navigation with conservative pacing.

### P0 — ImmoScout24 Austria

URL: https://www.immobilienscout24.at/

Why it matters:

- Austrian nationwide coverage;
- dedicated house-purchase search;
- useful structured fields such as price, living area, location and many property attributes.

Current observed scale during research: roughly 12,800 houses for sale nationwide on the dedicated house search.

Adapter path: **TBD after source-specific investigation**.

### P1 — immowelt.at

URL: https://www.immowelt.at/

Why it matters:

- Austrian property search by location or postal code;
- house/apartment purchase inventory;
- saved-search/email-alert functionality may provide an additional low-frequency discovery mechanism.

Adapter path: **TBD after source-specific investigation**.

### Later property candidates

Evaluate additional Austrian/regional portals and direct brokerage sites after the first three adapters establish the common normalization contract. Regional sources can be valuable because nationwide portals do not necessarily contain every listing.

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

That aggregation makes AMS an unusually high-value first job source.

Important distinction: the documented AMS HR-API found during research is an employer/recruiting-software interface for **submitting** vacancies to AMS, not a general public search API for downloading all vacancies. Do not mistake it for the acquisition interface we need.

Adapter path: investigate the current `alle jobs` search application and identify the safest structured/public interface available to normal search users.

### P0 — karriere.at

URL: https://www.karriere.at/

Why it matters:

- strong Austrian focus;
- many engineering/technical vacancies;
- useful location and compensation information;
- broad search terms such as Maschinenbau / Maschinenbauingenieur already surface many adjacent roles, which is useful for our non-exact matching model.

Current research pages returned more than 1,000 results for several mechanical-engineering-related searches.

Adapter path: **TBD after source-specific investigation**.

### P1 — StepStone Austria

URL: https://www.stepstone.at/

Evaluate as an additional nationwide professional-job source after the first job adapter works end-to-end.

### P1 — willhaben Jobs

URL: https://www.willhaben.at/jobs/

Potentially useful because WohnWerk may already maintain a willhaben browser/source integration for property data, while job data still remains a separate adapter and normalization path.

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

- Austrian government equal-treatment guidance: https://www.oesterreich.gv.at/en/themen/gesetze_und_recht/frauenfoerderung-und-gleichbehandlung/gleichbehandlung/1/2/Seite.1860220
- Arbeiterkammer guidance: https://www.arbeiterkammer.at/beratung/arbeitundrecht/Gleichbehandlung/Gleichbehandlungsgesetz.html

This makes advertised compensation unusually useful for automated job comparison, but the amount may be only a collective-agreement minimum rather than the likely final salary.

## 13th/14th salary caution

Do not automatically multiply every monthly salary advertisement by 14.

Holiday and Christmas special payments are common in Austria and are often governed by collective agreements, but Arbeiterkammer explicitly notes that there is no universal statutory entitlement in ordinary private employment when neither the applicable collective agreement nor the individual contract provides them.

Reference: https://www.arbeiterkammer.at/beratung/arbeitundrecht/arbeitsvertraege/Weihnachts-Urlaubsgeld.html

The parser should preserve the raw compensation text and only derive an annual figure when the payment basis is sufficiently clear.

## Postal-code reference data

### P0 — Austrian Open Data PLZ dataset

Dataset: https://www.data.gv.at/datasets/f76ed887-00d6-450f-a158-9f8b1cbbeebf

Publisher: RTR-GmbH

License: CC BY 4.0

The dataset contains Austrian postal codes (including valid/historical entries) and their associated postal-code names. The data.gv.at record was updated in 2025.

Use this as the canonical PLZ/name seed. A separate enrichment/import step will provide approximate centroid coordinates suitable for PostGIS distance matching.

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
structured normal-user endpoint
        ↓
static HTML parsing
        ↓
Playwright/browser automation
```

The source layer should behave conservatively: small concurrency, incremental discovery, backoff on errors/rate limits, and no repeated full-history requests when a newest-first incremental strategy can stop at already-known source IDs.
