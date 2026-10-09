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
The read-only `/health` response reports `road_routing_mode=air_distance_only`
while routing is disabled or DE graph coverage has not been declared, and
`de_graph_declared` if the operator explicitly enables it. The latter is
a configuration declaration, **not proof that the server loaded the right graph**.

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
4. Start the Germany OSRM service and execute the **read-only** probe
   `python -m scripts.check_osrm_germany --base-url http://127.0.0.1:5000`.
   It checks five long intercity routes between München, Berlin, Hamburg,
   Köln and Dresden, verifying snap distances and intentionally permissive
   road-distance bands. Then independently check actual `/table/v1/driving`
   queries with German properties from the database, inspect waypoint snap
   distances and compare kilometres against an independent road-route
   reference. A passing script alone is **not** authority to enable routing.
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
cached. A visible **Hausnummer erneut prüfen** button deliberately retries
an unverified workplace address; editing the address also initiates a new attempt.
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

Both are **manual diagnostics only**, and neither is automatically scheduled.
Live bounded adapter GETs and selected detail-page checks on 2026-10-09
confirmed **six source-advertised existing houses**, an auction correctly
rejected, and a holiday property without primary-residence eligibility
correctly withheld. The complete reproducible counts, original ad IDs,
GitHub Actions log links and confidence limits are in
[public portal live acceptance](public-portal-live-acceptance-2026-10-09.md).
**No production database ingestion or complete-source scan has occurred.**
Manual enablement still requires operator review of website terms, real
incremental yield and rate/access behavior. Available public entry points:

- `ohne-makler.net`: one national **purchase-only** `/immobilien/haus-kaufen/`
  frontier and nine purchase-only federal-state frontiers: Bayern,
  Baden-Württemberg, Rheinland-Pfalz, Nordrhein-Westfalen, Sachsen,
  Sachsen-Anhalt, Brandenburg, Mecklenburg-Vorpommern and Thüringen.
- `immobilien.de`: one national and four city frontiers: Neubrandenburg,
  Gangelt, Homburg and Hagenow.

A **critical quality risk** was confirmed by manually opening an under-€200k
immobilien.de listing: its detail was a hypothetical house-building offer,
with **land and additional costs excluded**. An inexpensive search card alone
is *not* proof of an existing, purchasable house. All leads from these two
new providers now carry a fail-closed `public_house_detail_required` flag
and are **excluded from accepted results until verified individually**.

The optional low-rate detail check requires the original listing ID, matching
German PLZ, matching asking price (not €/m²), evidence of an existing built
house and its land, and no explicit construction-only/house-without-land terms.
If the detail is blocked, ambiguous, missing, or exceeds the bounded request
cap, the lead is retained as **unverified/hidden** instead of accepted. This
policy is deliberately conservative: it may withhold some real houses that
do not expose sufficient public details. No contact data, pages, images or
owner details are retained. One shard reads the first public search page;
the optional detail check reads at most eight eligible details per shard by
default, with >=2-second spacing. Neither source can prove disappearance.

For a reproducible **offline/no-network** reproduction of a search parser issue,
save one public HTML page locally (without login) and run
`python -m scripts.inspect_public_portal_snapshot_de --provider immobilien-de
--frontier de-neubrandenburg --html-file /tmp/public-search.html`.
It lists candidate IDs and always reports `production_activation_ready=False`;
HTML files and provider contact details are never committed to the repo.

Use the **read-only, database-free** live diagnostic in two stages:

1. `python -m scripts.inspect_public_portals_de --provider all` to inspect
   the two national first-page frontiers without accessing details. It labels
   those leads **unverified**, even if within the price budget.
2. `python -m scripts.inspect_public_portals_de --provider all --regional
   --verify-details --max-detail-checks 4` to check the whitelisted regions
   and a few individual public details per shard. It reports distinct budget
   IDs, verified built houses and rejection reasons. An access restriction
   stops further attempts at that provider, without bypass.

Only after operator review of site terms, diagnostic output and incremental
yield should an authorized operator run the **database-writing**
`python scripts/run_ohne_makler_de.py` or
`python scripts/run_immobilien_de.py`. Those manual runners request the
bounded detail checks and save nonverified items only as hidden observations.
No new provider is automatically scheduled. A provider with zero verified
built houses should not be promoted to production coverage.
