# Germany-only house search and commute routing (2026-10-09)

WohnWerk's active acquisition scope is Germany only. Work destination is configured in the
private candidate profile (currently: **Ambossstraße 4, 80997 München**).

## Root cause and fail-closed fix

The previous checked-in OSRM systemd unit pointed to a non-German routing extract.
OSRM Table can return a formally successful driving distance after snapping out-of-graph
coordinates to a distant reachable road, introducing errors on the order of hundreds of km.

The Germany-only unit now expects `/var/lib/osrm/germany-latest.osrm`. The Python
application does **not** infer that the live OSRM service actually loaded that graph.
By default `WOHNWERK_ROUTING_GRAPH_COUNTRIES` is empty, which withholds road km/min
until an operator verifies the new graph and explicitly sets it to `DE`.

In addition, the router rejects a source snapped more than 3000 m away, marks
individual far-snapped destinations unreachable, and rejects physically impossible
route distances shorter than the geodesic lower bound. Failed routing retains
separately labeled straight-line km; it never substitutes them for road km.

## Operator-only OSRM cutover (not performed by code/PR)

1. Download a legitimate and current **Germany** `.osm.pbf` extract from a
   trusted provider (for example Geofabrik). Check its integrity and permissions.
2. Build the Germany **car-profile, MLD** OSRM graph in a staging location using
   `osrm-extract -p <car.lua> germany-latest.osm.pbf`,
   `osrm-partition germany-latest.osrm`, and
   `osrm-customize germany-latest.osrm`.
3. Ensure the new files are readable by the `osrm` user. Before replacing the
   active service, verify disk/RAM budgets and retain a rollback copy of the
   old service/unit/data. Stop and replace via the approved deployment process.
4. Start the Germany OSRM service and check actual `/table/v1/driving` queries
   with Munich and several geographically separated German properties. Inspect
   waypoint `distance` snap values and compare kilometres against an independent
   road-route reference, not merely the OSRM `code=Ok` response.
5. **Only then** set `WOHNWERK_ROUTING_GRAPH_COUNTRIES=DE` in the application
   environment and restart the web service; verify German km and road minutes
   plus intentionally unrouteable rows. If validation fails, do not enable
   the flag.

There is no database migration. Older workplace records currently retain the
**80997 postal centroid** until address geocoding is explicitly opted in and
a full, manually entered street address is re-saved. A PLZ centroid is
always displayed as approximate; it is never claimed to be door-to-door.

## Operator-controlled street-address geocoding (not enabled on the server)

Setting `WOHNWERK_WORKPLACE_GEOCODING_ENABLED=true` permits a **manual
workplace settings save** to send the *workplace address* to the configured
geocoder, defaulting to the public OSM Nominatim service. This can disclose
the address and IP to a third party; review privacy expectations first. No
property listings, jobs, bulk lookups, or page-load refreshes invoke it.
The request supplies a distinct application User-Agent, requests at most
five candidates in one search, is throttled on a per-process basis, and
stores verified or unverified outcomes to avoid repeat queries on unchanged
text. Do not configure multiple independent public-API workers without
a **shared** rate limit. The public service allows at most 1 request/second,
requires attribution and identifiable User-Agent, and can change its
availability; see https://operations.osmfoundation.org/policies/nominatim/.

Only a returned matching `DE` country, 5-digit PLZ, road and **house number**
within 15 km of the known PLZ centroid is accepted as street-level evidence.
Multiple far-apart candidates are rejected. A failed or incomplete match
keeps PLZ-level coordinates labeled **approximate**. Existing identical
street addresses saved before opt-in are checked once after opt-in and then
cached. Correcting or changing the saved address initiates a new attempt.
Road **distance** still independently requires the Germany OSRM cutover
and its explicit graph-coverage setting; enabling the geocoder alone does
not silently enable routing.

When street coordinates are accepted, the UI displays OpenStreetMap
attribution; these coordinates are not evidence that every property
has a precise location.

## Additional German property providers

Two independent public-card adapters have been added:

- `ohne-makler-de`: public house frontier at `ohne-makler.net`.
- `immobilien-de`: public German houses at `immobilien.de`.

Both are **manual diagnostics only** until source terms, actual HTML,
card extraction, and worthwhile in-budget yield have been checked live.
The Ohne-Makler entry uses its **purchase-only** `/immobilien/haus-kaufen/`
frontier (not the mixed sale/rental listing). Immobilien.de has one national
and four public city landing pages: Neubrandenburg, Gangelt, Homburg, Hagenow.
These pages and example under-€200k listings were verified as publicly
visible on 2026-10-09; **no real HTML crawl/ingest test was run**. Each shard
requests only the first listing page, and duplicates are keyed by stable
source listing IDs. The frontiers do not require accounts or contact forms
and are never authoritative for disappearance. A new crawler cannot be
counted as production coverage just because its code exists.

Diagnostic operators can use:
`python scripts/run_ohne_makler_de.py` and
`python scripts/run_immobilien_de.py`, through the usual authorization and
runtime gates. Do not schedule these automatically on first deployment.
