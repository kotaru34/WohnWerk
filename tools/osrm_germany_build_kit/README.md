# WohnWerk Germany OSRM build kit

Build and acceptance-test a full Germany **MLD** road graph away from the small
production VPS. The preferred Windows path is MSYS2 + Docker Desktop/Podman; the
same Python commands work on Debian with Docker/Podman.

Pinned routing engine: `ghcr.io/project-osrm/osrm-backend:26.10.0-debian`.
The builder records the actually resolved image digest in the output manifest.

## Host requirements

- Python 3.11+
- Docker or Podman accessible from the current shell
- Germany PBF is ~4.5 GB; reserve **at least 60 GB free disk**, preferably 100 GB
- Give the container runtime substantial RAM. 32 GB+ is a practical starting point
  for a Germany build. The script warns instead of pretending an exact peak is known.
- MSYS2: Docker Desktop/Podman must already be working from the MSYS2 shell.
  The script uses `cygpath` automatically for Windows volume paths.
- Debian: Docker Engine/Podman works directly.

## Build

From this directory:

```bash
python build.py --work-dir ./work
```

This will:
1. download `germany-latest.osm.pbf` and Geofabrik's MD5 file;
2. verify MD5 and compute SHA-256;
3. pull the pinned OSRM image and record its resolved digest/version;
4. run `osrm-extract`, `osrm-partition`, `osrm-customize`;
5. start the just-built graph locally;
6. run strict five-city acceptance probes;
7. record container memory usage while the graph is loaded;
8. create `wohnwerk-osrm-germany-manifest.json`.

No WohnWerk server is contacted.

## Package

After a successful build:

```bash
python package.py --work-dir ./work
```

Creates a ZIP64 package containing the manifest and every
`germany-latest.osrm*` graph artifact. It also writes a SHA-256 file for the
package.

## Independent re-check

```bash
python verify.py --base-url http://127.0.0.1:5000
```

The acceptance probes require close road-network snaps, nonnegative table
metrics, a route no shorter than the geodesic lower bound (within snap
allowance), plausible effective speed, and broad route-distance bands for
München/Berlin/Hamburg/Köln/Dresden.

## Production boundary

Copying the package to WohnWerk is **not activation**. A separately authorized
Sentinel operation must:

- verify package checksum + manifest;
- stage under a new inactive directory;
- measure actual `osrm-routed` resident memory on the target;
- refuse local activation if the ~4 GiB host has inadequate headroom;
- install the Germany service or point `WOHNWERK_ROUTING_BASE_URL` at a
  stronger remote router;
- run `scripts/check_osrm_germany.py` against the running service;
- only then set `WOHNWERK_ROUTING_ENABLED=true` and
  `WOHNWERK_ROUTING_GRAPH_COUNTRIES=DE`.

Do not copy only a file named `.osrm`: modern OSRM datasets are a collection
of `.osrm.*` files sharing one base prefix.
