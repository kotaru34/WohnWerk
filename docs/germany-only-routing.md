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

There is no database migration. Existing workplace storage is based on the
**80997 postal centroid**, not confirmed house-level coordinates; it must
continue to be labeled approximate until a separate street-level geocoding
step is verified. Never claim door-to-door precision from postal centroids.

## Additional German property providers

Two independent public-card adapters have been added:

- `ohne-makler-de`: public house frontier at `ohne-makler.net`.
- `immobilien-de`: public German houses at `immobilien.de`.

Both are **manual diagnostics only** until source terms, actual HTML,
card extraction, and worthwhile in-budget yield have been checked live.
They do not require creating an account, do not access contact forms or
private pages, and are never authoritative for disappearance. A new crawler
cannot be counted as production coverage just because its code exists.

Diagnostic operators can use:
`python scripts/run_ohne_makler_de.py` and
`python scripts/run_immobilien_de.py`, through the usual authorization and
runtime gates. Do not schedule these automatically on first deployment.
