# WohnWerk

Private self-hosted **Germany-only** house-discovery and suitability system.

## Scope

- Current country: Germany (`DE`), purchase price target **€30,000–200,000**.
- Profile-managed German postcode exclusions, hospital and internet checks, heating
  preferences, favourites and visibility states.
- User-configured workplace address (currently Ambossstraße 4, 80997 München) and
  house-to-work distances. The stored workplace point currently uses the **postal
  centroid**, not a verified door-level coordinate.
- Germany job acquisition remains paused.

## German property discovery

Current production-validated scheduled German sources include `kleinanzeigen-de`,
`engel-voelkers-de`, `iad-de`, and `falc-de`. The Immowelt path is provider-
restricted and must fail closed; ImmoScout24, VON POLL and RE/MAX are manual
diagnostics only pending valid public access.

The open regional Kleinanzeigen change is under PR #60; it is not assumed deployed.
Two additional account-free direct portal adapters are staged under PR #61:
`ohne-makler-de` and `immobilien-de`. They are **manual diagnostics**, not
production-scheduled or live-validated sources.

Source identities and URLs are preserved. A bounded public search frontier never
proves that a missing ad has been removed. No guessed prices, house coordinates,
source area semantics, or source liveness.

## Safe commute routing

Only use OSRM kilometres/minutes after the actual server loads a Germany road graph.
The checked-in service expects `/var/lib/osrm/germany-latest.osrm`. Road routing
requires explicit `WOHNWERK_ROUTING_GRAPH_COUNTRIES=DE` **after** validating the
actual OSRM dataset and waypoint snapping. Unreliable routes are withheld, leaving
a separately labelled straight-line metric. See
[`docs/germany-only-routing.md`](docs/germany-only-routing.md).

## Setup and rollout

See `docs/germany_mvp.md`, `docs/acquisition.md`, and `docs/sources.md`
for implementation/retention policies. Each release requires an exact-head
successful CI gate and a separately authorized production deployment. A GitHub
pull request does not imply an active source or deployed server change.
