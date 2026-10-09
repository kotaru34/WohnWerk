# Germany routing production gate — signed read-only host inspection (2026-10-09)

**Audit scope:** WohnWerk PR #61 only, target `wohnwerk`, issue-scoped
Tethys Sentinel GitHub relay session. **No production changes performed.**
Do not publish relay secrets, session authenticators, private `.env` content,
database URL, host credentials or temporary sudo policy in public logs.

## Direct host evidence

- `/health`: HTTP 200, version **0.4.30**, effective country **AT**.
- `/opt/wohnwerk`: exact HEAD `a26ca2b79799ba82bdecc30896d45267ff2cf511`, clean.
- `wohnwerk.service`, `wohnwerk-osrm.service`, Caddy all active.
- The installed `wohnwerk-osrm.service` runs
  `/usr/local/bin/osrm-routed /var/lib/osrm/austria-latest.osrm
  --algorithm MLD --mmap ...`.
- **No** `germany-latest.osrm`, `.partition` or `.cells` artifacts
  appeared at the expected Germany paths.
- Host resources: approx **3.8 GiB total RAM**, **3.2 GiB available** at
  inspection, **1.6 GiB swap**, **16 GiB free disk**.
- `osrm-routed` installed at `/usr/local/bin/osrm-routed`, but no
  `osrm-extract`, `osrm-partition` or `osrm-customize` were found.
- `sentinel-ai` permanent sudo only permits the named
  `tethys-sentinel-consume` command. It **cannot** install builders,
  replace root-owned OSRM data, change systemd or update `/opt/wohnwerk`.
- A **pinned, isolated clone** of PR #61 ran
  `scripts/audit_germany_routing_host.py` on the actual target with no DB,
  sudo or running-service writes. It correctly returned nonzero and
  pinpointed country AT, Austria OSRM unit, missing DE graph files and
  unapproved DE routing state. Its first run also exposed a harmless PATH
  false negative for `osrm-routed`; the audit now explicitly finds
  `/usr/local/bin` even when the relay sanitizes PATH.

Sources: [Relay authorization and response thread](https://github.com/kotaru34/tethys-sentinel-github-relay/issues/117);
[PR #61](https://github.com/kotaru34/WohnWerk/pull/61).
The thread contains the actual signed command phases, but never the
out-of-band session secret.

## Why direct OSRM Germany build on this VPS is not approved

Geofabrik's complete Germany `.osm.pbf` weighs approximately **4.5 GB**:
https://download.geofabrik.de/europe/germany.html.
OSRM's own memory guidance shows substantially larger preprocessing memory
demands than PBF bytes:
https://github.com/Project-OSRM/osrm-backend/wiki/Disk-and-Memory-Requirements.
Actual needs depend on profile, version, RAM and preprocessing algorithm.

A full national MLD build must therefore be performed on a separate
appropriately provisioned build machine (or approved larger temporary VM)
with the exact compatible OSRM toolchain, sufficient memory and scratch
storage. Do **not** attempt it on a ~4 GiB production host while the
app and old OSRM are serving requests. Upload/copy only validated output
through the operator-approved channel, with checksums and suitable
ownership. Full Germany runtime graph memory requirements must also be
measured before promising this 4 GiB VPS can host it; staging success alone
does **not** establish that it can fit.

## Required cutover prerequisites

1. Authorize an **explicit, time-bounded operator sudo bootstrap**, independently
   from this read-only Relay session, using the existing Sentinel approval
   process. Do not broaden `tethys-sentinel-consume` to an arbitrary
   shell. Reconfirm the exact production HEAD and clean worktree.
2. Prepare full Germany OSRM MLD artifacts on an external build host or
   provision a genuinely sufficient target, with known OSRM versions
   and original data integrity checked. Check memory and disk on both
   build and serving hosts. Preserve the working Austrian graph, unit and
   release as rollback until DE acceptance is complete.
3. Stage and verify the checked-in Germany `wohnwerk-osrm.service` template,
   then conduct **five separated German city routes** with
   `python -m scripts.check_osrm_germany`, including a real property-to-
   München workplace sample and snap distances. Fail closed if any target
   is outside the German road graph.
4. Plan an independently reviewed sequential release of stacked PR #60 and
   PR #61, including Alembic checks, backup, and actual source-data
   compatibility. Review operator authorization before merge or promotion.
5. Update protected environment to `WOHNWERK_COUNTRY_CODE=DE` and only
   set `WOHNWERK_ROUTING_GRAPH_COUNTRIES=DE` after validating the
   *running* Germany OSRM graph. Do not enable third-party address
   geocoding until the operator expressly consents.
6. Validate `/health`, effective country, DE road kms and minutes, country-
   scoped catalogue, scheduler states, raw/verified source visibility and
   unchanged production data. Revoke temporary sudo as the final
   privileged deployment action.

**Safety:** under the currently granted access, only the *preflight* steps
above were performed. Nothing here represents a production deployment,
permission to retry CAPTCHA, or a successful German OSRM acceptance.
