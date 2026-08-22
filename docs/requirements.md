# WohnWerk Requirements

## Product goal

Provide one local web application that helps evaluate where to live and work in Austria by combining:

- houses for sale that satisfy explicit property criteria;
- job vacancies that are plausibly suitable for an experienced mechanical-engineering professional with a broad work history;
- configurable geographic matching between the two.

The application is intended to replace repeated manual searches across many portals, not to reproduce or redistribute the portals themselves.

## Property requirements

### Hard filters

The UI and backend must support at least:

- minimum purchase price;
- maximum purchase price;
- minimum living area (`Wohnfläche`);
- minimum plot/land area (`Grundstücksfläche`);
- Austrian postal code;
- city/locality;
- active/inactive listing state.

Exact target values are runtime/user configuration, not hard-coded constants.

### Optional/soft property data

Where available:

- description;
- property type;
- room count;
- construction year;
- condition / renovation state;
- garage / parking;
- cellar;
- workshop / outbuilding;
- garden;
- optional keyword matches;
- price-history events.

Missing optional data must not automatically reject a property.

### Provenance and history

For every source listing preserve:

- source name;
- source listing ID;
- original URL;
- first seen;
- last seen;
- inactive timestamp where known;
- raw source payload/snapshot where practical.

Canonical properties must support more than one source listing.

## Job requirements

### Candidate discovery

Initial search phrases may include terms such as `Maschinenbauingenieur`, but job discovery must not depend on exact title matching.

The system should also find adjacent plausible roles such as construction/design engineering, product development, project engineering, technical specialist work, machine/plant engineering, and other roles inferred from the manually curated professional profile.

### Stored job data

At minimum:

- title;
- employer;
- description;
- one or more locations;
- Austrian postal code where available;
- salary text exactly as advertised;
- normalized salary fields where reliable;
- source(s) and original URL(s);
- first/last seen and active state;
- `job_fit_score` from 0 to 100;
- extracted skills/features when enrichment is available.

### Salary semantics

The system must distinguish:

- explicitly advertised amount;
- collective-agreement/minimum amount;
- salary range;
- willingness to overpay (`Überzahlung`);
- derived/normalized annual value;
- unknown or ambiguous compensation.

Unknown salary should normally be neutral rather than a strong negative ranking signal.

### Professional profile

Skills/features should eventually support at least two dimensions:

1. experience/ability;
2. preference/willingness.

Example experience states:

- strong;
- some experience;
- willing to learn;
- unsuitable / not relevant.

Example preference states:

- prefer;
- neutral;
- avoid.

These dimensions must not be collapsed into one irreversible boolean.

### Feedback

A later iteration should allow direct feedback on a vacancy, for example:

- suitable;
- neutral;
- unsuitable.

Feedback may inform future ranking but must not destroy the original deterministic feature data.

## Geographic matching

### Location model

The minimum reliable location unit is the Austrian four-digit postal code.

The database will associate postal codes with approximate centroid coordinates and store PostGIS `geography(Point, 4326)` values for spatial queries.

### Required interactions

From a selected property:

- show jobs within 25 km;
- show jobs within 50 km;
- show jobs within 100 km;
- show jobs within a custom radius.

From a selected job/location:

- show houses using the same radius choices.

Distance is straight-line geographic distance, not road-routing distance.

### Scoring separation

`job_fit_score` is independent of geography.

A future house/job pair score may include distance but must be computed for the selected pair/context rather than stored as the intrinsic job score.

## Source ingestion requirements

- many sources are a first-class requirement;
- each source has an isolated adapter;
- source-specific polling intervals and pacing;
- incremental discovery where possible;
- deduplication across sources;
- status checks where practical and proportionate;
- no deletion of historical records merely because an external listing disappears;
- failure of one source must not stop other sources;
- failure of the optional AI service must not stop core ingestion.

## UI requirements

Primary navigation:

```text
Häuser | Jobs | Matching | Profil / Skills | Sources
```

Property browsing must support sorting/filtering by at least:

- price;
- living area;
- plot area;
- postal code;
- city;
- newest/first seen;
- active state.

Job browsing must support sorting/filtering by at least:

- job fit score;
- salary;
- postal code;
- city/location;
- newest/first seen;
- active state.

The UI should expose source links and should remain understandable to a non-technical user.

## Non-functional requirements

- self-hosted on the existing home infrastructure;
- local-network web UI;
- PostgreSQL as source of truth;
- PostGIS for geographic queries;
- graceful handling of missing fields;
- deterministic core operation without GPU/AI;
- source adapters independently testable;
- conservative external request behavior;
- maintain sufficient logging to debug failed adapters without logging secrets/cookies.
