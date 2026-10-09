# German public house adapters: bounded live acceptance — 2026-10-09

This is evidence for **manual read-only acceptance of public HTML adapters**, not
a production crawl, OSRM cutover, legal authorization for recurring harvesting,
or guarantee that an advertised property remains available.

## Environment and verification

- GitHub-hosted ephemeral runner, Python 3.12, source branch
  `fix/workplace-de-routing-coverage` (draft PR #61).
- Public **GET** only; no account, cookie challenge bypass, contact extraction,
  private database, or production VM. Only the first page of each listed
  search frontier was fetched, followed by at most **two** public detail
  pages per manually selected shard.
- Original listing URL, provider-issued ID, postcode, asking price,
  living/plot area and building year were checked against the public detail.
  Unverified, auction and non-primary-residence advertisements stayed excluded.
- The transient PR-only live-smoke CI step was removed after these observations.
  Normal PR CI now remains wholly offline/deterministic. Reproduce live
  acceptance **manually** using `scripts/inspect_public_portals_de.py`
  after checking source conditions and operational authorization.

## Observed results (live HTML, not synthetic fixtures)

| Workflow run | Public search frontier | Identifiable listing cards | In-budget cards | Details checked | Existing-house evidence accepted |
|---|---|---:|---:|---:|---:|
| [37864633898](https://github.com/kotaru34/WohnWerk/actions/runs/37864633898) | ohne-makler national | 24 | 0 | 0 | 0 |
| [37864633898](https://github.com/kotaru34/WohnWerk/actions/runs/37864633898) | immobilien.de national | 24 | 2 | 0 | 0 |
| [37864774076](https://github.com/kotaru34/WohnWerk/actions/runs/37864774076) | ohne-makler Mecklenburg-Vorpommern | 24 | 5 | 2 | 1 |
| [37864774076](https://github.com/kotaru34/WohnWerk/actions/runs/37864774076) | immobilien.de national | 24 | 2 | 2 | 2 |
| [37865028829](https://github.com/kotaru34/WohnWerk/actions/runs/37865028829) | ohne-makler Thüringen | 24 | 9 | 2 | 2 |
| [37865028829](https://github.com/kotaru34/WohnWerk/actions/runs/37865028829) | immobilien.de Gangelt | 24 | 2 | 2 | 1 |

### Property-level evidence and failures

- **Verified existing-house evidence** on sampled public pages:
  `ohne-makler.net/immobilie/503088/` (€120,000), `501305/` (€189,000),
  `490242/` (€159,000); `immobilien.de/expose/9658417` (€185,000),
  `10052469` (€169,000) and `9720718` (€159,000).
  Verification confirms that the *public advertisement* provides matching
  house/plot/price evidence, **not** ownership, legal status, price accuracy,
  or current availability.
- **Deliberately rejected:** ohne-makler `503042` (€135,000) explicitly
  unsuitable for permanent residence; immobilien.de `10038613`
  (€156,000) is a compulsory-auction advertisement. Neither should surface
  as an ordinary residence offered for a fixed asking price.
- **Real bug caught and fixed:** the first detail acceptance run rejected
  Ohne-Makler `503088` as `land_area_unverified`. Its public page renders
  `2.912 m² Grundstücksfläche` rather than the reverse label/value order
  used by another provider. The verifier now accepts **either explicit
  label order**, with numeric area and house-price bounds. Retest:
  `verified_existing_house`. Added permanent regression coverage.
- **Extra false-positive boundary:** public immobilien.de detail pages can
  include unrelated offers in recommendation carousels. The verifier now
  truncates recommendation sections before extracting building facts.
  It also rejects auctions and implausibly small living/land measurements.

## Status / operational decision

1. **Public frontend connectivity and parser viability:** demonstrated for
   national Ohne-Makler and immobilien.de, regional Ohne-Makler in
   Mecklenburg-Vorpommern and Thüringen, and immobilien.de Gangelt.
2. **Actual sample quality:** six first-hand, detail-checked advertisements
   passed conservative source-evidence verification; an auction and a
   residence-restricted holiday property were correctly rejected. Additional
   unsampled cards remain unknown/unverified.
3. **Production automation:** **NOT APPROVED**. Other regional first pages
   need real-adapter acceptance and differentiated unique-ID yield; source
   conditions and site access behavior need ongoing operator review.
   Never treat first-page absence as a removal event.
4. **No user data or private server was accessed** in these tests.

See `docs/germany-only-routing.md` for the independent Germany OSRM and
workplace-address deployment gates.
