# WohnWerk job discovery and house/job matching model

This document records the central product loop. It is a product invariant, not an implementation suggestion.

## 1. The local job corpus is broad but already relevant

WohnWerk must **not** fill PostgreSQL with every vacancy in Austria.

External acquisition may search very broadly, but a vacancy enters the durable local job corpus only when it satisfies both of these coarse requirements:

1. it is an Austrian vacancy/location; and
2. it is plausibly inside the broad target professional neighbourhood according to deliberately high-recall base title/keyword signals.

The desired scale is not a small hand-picked shortlist. The target is a large corpus — potentially on the order of 10,000 relevant active vacancies when source coverage permits — while excluding obviously unrelated work such as accounting, HR, retail, hospitality, etc.

The pre-ingestion gate is intentionally **not** the final suitability algorithm. It should err toward retaining plausible adjacent technical roles.

Initial seed vocabulary includes concepts such as:

- Maschinenbau / Maschinenbauingenieur
- Konstruktionsingenieur / Konstruktion
- Entwicklungsingenieur
- Mechanical Engineer / Mechanical Design Engineer
- CAD-Konstrukteur
- Berechnungsingenieur
- Produktentwicklung
- Sondermaschinenbau
- Application Engineer when supported by mechanical/engineering context
- Project/Projekt engineering when supported by mechanical/engineering context
- CAD
- Creo
- SolidWorks
- CATIA
- Inventor
- Siemens NX
- Blechkonstruktion
- FEM / Berechnung
- Anlagenbau

This vocabulary is a discovery seed, not a permanent closed taxonomy.

## 2. The corpus teaches WohnWerk new concepts

After broad-relevance vacancies are stored, WohnWerk extracts recurring useful concepts from the corpus.

A concept is not every token/word. It is a normalized semantic feature useful for discovery or ranking, for example:

- job title or title family;
- skill;
- software/tool;
- engineering discipline;
- manufacturing/design specialization;
- recurring technical responsibility.

Examples:

- `Konstruktionsingenieur`
- `CAD-Konstrukteur`
- `Creo`
- `Blechkonstruktion`
- `Sondermaschinenbau`
- `FEM`
- `Produktentwicklung`

Aliases and morphological variants should be able to map to one normalized concept while preserving their source evidence.

Concept extraction may combine deterministic rules, aliases, corpus statistics/co-occurrence, embeddings/classification, and optional AI enrichment. AI output must remain evidence/suggestion rather than silently becoming user preference.

Each concept must retain provenance/evidence showing why it was attached to a vacancy.

## 3. Human review converts discovered concepts into a professional profile

Automatically discovered concepts are **not** automatically considered desirable.

The `Profil / Skills` UI presents unique normalized concepts to the job seeker for review. The profile must preserve at least two independent dimensions:

### Ability / experience

Conceptually:

- can / experienced;
- partial experience;
- cannot yet / no experience.

### Willingness / preference

Conceptually:

- want / prefer;
- willing to learn / willing to do;
- neutral;
- do not want / avoid.

The storage model should keep the dimensions independent rather than collapsing them into one irreversible enum. The UI may present convenient combined states such as:

1. **I can do this and want to do it**;
2. **I cannot do this yet, but I am willing to learn it**;
3. **I can do this, but I do not want to do it**;
4. **I cannot do this and do not want to do it**.

Unreviewed concepts are neutral. They must not silently become positive or negative signals.

## 4. Vacancy fit is recomputed locally

Every relevant vacancy is associated with its extracted concepts and evidence.

When the user changes a concept assessment, WohnWerk can recompute suitability for the whole local job corpus without re-crawling external sources.

The resulting intrinsic `job_fit_score` should answer roughly:

> Given the reviewed professional profile, how suitable/desirable is this job itself?

It must remain independent of geography and independent of a particular house.

The score must remain inspectable: the UI should eventually be able to explain which concepts raised or lowered the result.

Direct vacancy feedback (`suitable`, `neutral`, `unsuitable`) may later tune ranking, but must not overwrite the explicit concept profile or raw extracted evidence.

## 5. Houses and jobs form a many-to-many recommendation space

The product is **not** intended to find only one job/house pair.

For every suitable house there may be many plausible jobs nearby, and for every suitable job there may be many plausible houses nearby.

Use PostGIS to create the candidate neighbourhood dynamically:

- house -> jobs within 25 / 50 / 100 / custom km;
- job -> houses within the same radii.

Do not precompute a permanent NxM matrix.

For each candidate house/job combination, keep separate dimensions such as:

- intrinsic job suitability;
- property suitability according to house criteria;
- geographic distance;
- salary/compensation evidence where useful;
- optional user-configurable pair preferences.

A contextual pair score may combine these dimensions for ranking, but it must not overwrite the underlying intrinsic scores.

The UI should therefore be able to present:

- a house with many ranked nearby jobs;
- a job with many ranked nearby houses;
- globally strong house/job combinations;
- filters/radii/settings that can change the recommendation set without re-ingestion.

## 6. Acquisition breadth is required, but irrelevant storage is not

Many independent job sources are a first-class product requirement because the relevant target corpus should be large enough to expose uncommon adjacent roles and meaningful geographic alternatives.

Lack of an official API by itself is not a reason to reduce the product to a tiny set of vacancies. Source acquisition methods should be evaluated individually: documented feeds/APIs are preferred where available; ordinary low-rate HTTP/browser acquisition may be used where appropriate. Explicit access restrictions or anti-bot barriers must not be bypassed; instead, missing coverage should be composed from other boards, employer career sites, ATS feeds, public-sector sources, agencies, and other legitimate layers.

The important product KPI is therefore **relevant Austrian vacancy coverage**, not raw worldwide/all-professions record count and not merely the number of configured source adapters.

## 7. Pipeline summary

```text
external Austrian job sources
        |
        v
broad acquisition / source traversal
        |
        v
Austria location gate
        |
        v
high-recall base professional relevance gate
        |
        v
LOCAL RELEVANT JOB CORPUS
(thousands / potentially ~10k+, not every Austrian vacancy)
        |
        v
concept extraction + normalization
(title / skill / tool / discipline / role family)
        |
        v
unique concept registry + source evidence
        |
        v
manual profile review
(ability + willingness)
        |
        v
background/local job-fit rescoring
        |
        +--------------------------+
        |                          |
        v                          v
   relevant jobs               houses
        |                          |
        +------ PostGIS radius ----+
                   |
                   v
        many-to-many house/job candidates
                   |
                   v
        contextual pair ranking + UI
```

If an implementation makes the local database tiny by being too strict at discovery, it is wrong. If it fills the database with the entire unrelated Austrian labour market, it is also wrong. The intended operating point is **high recall inside a deliberately broad target-profession neighbourhood**.
